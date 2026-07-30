"""Tests for ``panopto.settings`` - the per-run contract and its persistence.

Why this file exists
--------------------
Two separate high-consequence jobs live in this module and neither had a test.

**1. It shares a settings file with the rest of the app.** Panopto config lives
under one ``"panopto"`` key inside ``canvas_downloader_settings.json``, which
the Settings dialog also writes. The save is a read-modify-write specifically
so the two cannot clobber each other - and "clobbered" here means the user's
Canvas token settings silently disappearing when they change a Panopto option.

**2. ``is_enabled(contract)`` decides whether a whole download phase runs.**
``app.py:_next_phase_after_courses()`` calls it to choose between the
``'panopto'`` phase and going straight to the completion screen, which is also
why ``'panopto'`` never appears as a literal status anywhere (see
tests/test_cancellation.py).

``infer_contract_from_manifest`` is the recovery path for a documented severe
silent failure: when a folder's stored contract went missing, sync fell back to
session-only toggles that reset to False on every launch, so the Panopto pass
was skipped forever and the user's setup appeared to have vanished with no
message. Artifacts on disk are proof the feature WAS configured, so an
all-False answer there is provably wrong.
"""

from __future__ import annotations

import json

import pytest

from panopto import settings as S


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """Redirect the shared settings file into a throwaway directory.

    ``_config_path`` imports ``get_config_dir`` lazily from ``shared.helpers``,
    so the patch has to land on the helpers module, not on this one.
    """
    from shared import helpers
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture()
def config_file(config_dir):
    return config_dir / "canvas_downloader_settings.json"


# ═══════════════════════════════════════════════════════════════════════════
# Load / save
# ═══════════════════════════════════════════════════════════════════════════

def test_defaults_are_returned_when_nothing_is_stored(config_dir):
    assert S.load_settings() == S.PANOPTO_DEFAULTS


def test_the_returned_shape_is_always_complete(config_file, config_dir):
    """A partial stored dict must still produce every key - callers index into
    this directly rather than using ``.get`` everywhere."""
    config_file.write_text(json.dumps({"panopto": {"output_mp4": True}}),
                           encoding="utf-8")
    loaded = S.load_settings()
    assert set(loaded) == set(S.PANOPTO_DEFAULTS)
    assert loaded["output_mp4"] is True
    assert loaded["output_mp3"] == S.PANOPTO_DEFAULTS["output_mp3"]


def test_legacy_and_unknown_keys_are_dropped(config_file, config_dir):
    config_file.write_text(
        json.dumps({"panopto": {"output_mp3": False, "old_option": "gone"}}),
        encoding="utf-8")
    loaded = S.load_settings()
    assert "old_option" not in loaded
    assert loaded["output_mp3"] is False


@pytest.mark.parametrize("stored", ['"a string"', '[]', '42', 'null'])
def test_a_non_dict_panopto_value_falls_back_to_defaults(config_file, config_dir, stored):
    config_file.write_text('{"panopto": %s}' % stored, encoding="utf-8")
    assert S.load_settings() == S.PANOPTO_DEFAULTS


def test_a_corrupt_settings_file_falls_back_to_defaults(config_file, config_dir):
    """Panopto config is a preference. A broken file must not stop the app."""
    config_file.write_text("{not json", encoding="utf-8")
    assert S.load_settings() == S.PANOPTO_DEFAULTS


def test_a_non_dict_root_falls_back_to_defaults(config_file, config_dir):
    config_file.write_text('["a", "list"]', encoding="utf-8")
    assert S.load_settings() == S.PANOPTO_DEFAULTS


def test_settings_round_trip(config_dir):
    assert S.save_settings({**S.PANOPTO_DEFAULTS, "model": "large-v3",
                            "language": "da", "device": "cuda"}) is True
    loaded = S.load_settings()
    assert (loaded["model"], loaded["language"], loaded["device"]) == \
           ("large-v3", "da", "cuda")


def test_saving_NEVER_clobbers_other_top_level_settings(config_file, config_dir):
    """THE reason the save is a read-modify-write.

    The Settings dialog owns other top-level keys in the same file. A plain
    overwrite here would delete them, and the user would find their Canvas URL
    and preferences gone after toggling a Panopto checkbox.
    """
    config_file.write_text(json.dumps({
        "canvas_url": "https://cbs.instructure.com",
        "debug_mode": True,
        "panopto": {"output_mp3": False},
    }), encoding="utf-8")

    S.save_settings({**S.PANOPTO_DEFAULTS, "model": "medium"})

    full = json.loads(config_file.read_text(encoding="utf-8"))
    assert full["canvas_url"] == "https://cbs.instructure.com"
    assert full["debug_mode"] is True
    assert full["panopto"]["model"] == "medium"


def test_saving_stores_only_the_known_shape(config_file, config_dir):
    S.save_settings({**S.PANOPTO_DEFAULTS, "stray": "value"})
    stored = json.loads(config_file.read_text(encoding="utf-8"))["panopto"]
    assert "stray" not in stored
    assert set(stored) == set(S.PANOPTO_DEFAULTS)


def test_saving_creates_the_config_directory(tmp_path, monkeypatch):
    from shared import helpers
    nested = tmp_path / "does" / "not" / "exist"
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(nested))
    assert S.save_settings(dict(S.PANOPTO_DEFAULTS)) is True
    assert (nested / "canvas_downloader_settings.json").exists()


def test_a_failed_save_reports_false_and_leaves_no_tmp(config_dir, monkeypatch):
    monkeypatch.setattr(os_replace_target(), "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    assert S.save_settings(dict(S.PANOPTO_DEFAULTS)) is False
    assert not list(config_dir.glob("*.tmp"))


def os_replace_target():
    """``panopto.settings`` calls ``os.replace`` through its own module import."""
    import os
    return os


def test_engine_settings_returns_only_the_persisted_engine_config(config_dir):
    """Model/language/device are the one-time setup; outputs and layout are
    per-run and must NOT leak out of here."""
    S.save_settings({**S.PANOPTO_DEFAULTS, "model": "medium", "output_mp4": True})
    eng = S.engine_settings()
    assert set(eng) == {"model", "language", "device"}
    assert eng["model"] == "medium"


# ═══════════════════════════════════════════════════════════════════════════
# Output helpers
# ═══════════════════════════════════════════════════════════════════════════

def test_active_outputs_lists_only_what_is_on():
    assert S.active_outputs({}) == []
    assert S.active_outputs({"output_mp3": True, "output_srt": True}) == ["mp3", "srt"]


def test_active_outputs_is_in_pipeline_order():
    """mp4 -> mp3 -> txt -> srt mirrors the order the work actually happens in,
    which is what the progress UI narrates."""
    everything = {k: True for k in
                  ("output_mp4", "output_mp3", "output_txt", "output_srt")}
    assert S.active_outputs(everything) == ["mp4", "mp3", "txt", "srt"]


@pytest.mark.parametrize("settings,expected", [
    ({}, False),
    ({"output_mp3": True}, False),
    ({"output_mp4": True}, False),
    ({"output_txt": True}, True),
    ({"output_srt": True}, True),
    ({"output_txt": True, "output_srt": True}, True),
])
def test_wants_transcription_only_for_text_outputs(settings, expected):
    """mp4/mp3 are a download+remux; only txt/srt need Whisper, and that is the
    difference between a fast run and a GPU one."""
    assert S.wants_transcription(settings) is expected


# ═══════════════════════════════════════════════════════════════════════════
# The contract
# ═══════════════════════════════════════════════════════════════════════════

def test_make_contract_coerces_its_flags_to_bools():
    c = S.make_contract(mp4=1, mp3=0, txt="yes", srt=None, layout="match")
    assert c["output_mp4"] is True and c["output_mp3"] is False
    assert c["output_txt"] is True and c["output_srt"] is False


@pytest.mark.parametrize("layout,expected", [
    ("match", "match"), ("separate", "separate"),
    ("nonsense", "match"), ("", "match"), (None, "match"),
])
def test_make_contract_coerces_an_unknown_layout(layout, expected):
    """Layout picks the on-disk destination. An unrecognised value must land on
    the safe default rather than being passed to a path builder."""
    assert S.make_contract(mp4=False, mp3=True, txt=False, srt=False,
                           layout=layout)["layout"] == expected


@pytest.mark.parametrize("contract,expected", [
    (None, False),
    ({}, False),
    ({"layout": "match"}, False),                       # layout alone is not an output
    ({"output_mp3": False, "output_txt": False}, False),
    ({"output_mp3": True}, True),
    ({"output_mp4": True}, True),
    ({"output_txt": True}, True),
    ({"output_srt": True}, True),
])
def test_is_enabled_decides_whether_the_panopto_phase_runs(contract, expected):
    """``app.py:_next_phase_after_courses()`` calls this to choose between the
    'panopto' phase and the completion screen. A false negative skips the whole
    feature silently; a false positive enters a phase with nothing to do."""
    assert S.is_enabled(contract) is expected


def test_extract_contract_takes_the_per_run_keys_only(config_dir):
    full = {**S.PANOPTO_DEFAULTS, "model": "large-v3", "output_mp4": True,
            "layout": "separate"}
    c = S.extract_contract(full)
    assert set(c) == {"output_mp4", "output_mp3", "output_txt", "output_srt",
                      "layout"}
    assert "model" not in c, "engine config must never be stored per folder"
    assert c["output_mp4"] is True and c["layout"] == "separate"


def test_compose_layers_the_contract_over_the_persisted_engine_config(config_dir):
    S.save_settings({**S.PANOPTO_DEFAULTS, "model": "large-v3", "device": "cuda"})
    composed = S.compose_settings(
        S.make_contract(mp4=True, mp3=False, txt=False, srt=False,
                        layout="separate"))
    assert composed["model"] == "large-v3"      # from the persisted JSON
    assert composed["device"] == "cuda"
    assert composed["output_mp4"] is True       # from the contract
    assert composed["output_mp3"] is False
    assert composed["layout"] == "separate"


def test_compose_derives_enabled_from_the_outputs(config_dir):
    on = S.compose_settings(S.make_contract(mp4=False, mp3=True, txt=False,
                                            srt=False, layout="match"))
    off = S.compose_settings(S.make_contract(mp4=False, mp3=False, txt=False,
                                             srt=False, layout="match"))
    assert on["enabled"] is True
    assert off["enabled"] is False


@pytest.mark.parametrize("contract", [None, {}])
def test_composing_from_no_contract_falls_back_to_the_DEFAULTS(config_dir, contract):
    """Pins what this actually does, which is NOT what it used to claim.

    ``compose_settings`` starts from ``PANOPTO_DEFAULTS``, and three of those
    outputs (mp3/txt/srt) are ON. So a None/empty contract composes to
    ``enabled=True`` with transcription requested - the opposite of the
    "yields a disabled config" the docstring asserted until this test was
    written, and of the comment in ``sync_ui.py`` that builds the sync batch
    settings with ``compose_settings(None)``.

    Why it is not currently a live bug, and why it is still a trap:
    ``panopto/runner.py`` resolves each target's outputs as
    ``target.get("settings") or settings``, so a target carrying a falsy
    contract inherits these batch settings and would transcribe recordings
    nobody asked for. The only thing preventing that today is an unrelated
    guard - ``sync_ui.py`` skips any pair with no user-selected recordings, and
    the one path that produces an empty contract (a Panopto analysis that
    raised) also produces no selectable recordings. Change either of those and
    this becomes reachable.

    If the fallback is ever hardened to "no outputs", invert this test rather
    than deleting it.
    """
    composed = S.compose_settings(contract)
    assert composed["enabled"] is True
    assert composed["output_mp3"] is True
    assert composed["output_txt"] is True
    assert composed["output_mp4"] is False
    assert composed["layout"] == "match"


def test_a_partial_contract_fills_the_gaps_from_the_defaults(config_dir):
    """Same mechanism, stated directly: a contract missing an output key gets
    the DEFAULT for it, not False. Every contract the module itself builds
    (``make_contract``, ``extract_contract``, ``infer_contract_from_manifest``)
    carries all five keys, so this only bites hand-written or truncated ones.
    """
    composed = S.compose_settings({"output_mp4": True})
    assert composed["output_mp4"] is True
    assert composed["output_mp3"] is True, "the gap was filled from the defaults"


def test_extract_then_compose_preserves_the_contract(config_dir):
    original = S.make_contract(mp4=True, mp3=True, txt=False, srt=True,
                               layout="separate")
    assert S.extract_contract(S.compose_settings(original)) == original


# ═══════════════════════════════════════════════════════════════════════════
# Recovery: inferring a lost contract from what is on disk
# ═══════════════════════════════════════════════════════════════════════════

def test_an_empty_manifest_infers_nothing():
    """Critical direction. A folder with no Panopto artifacts never had the
    feature configured, and inventing a contract would start downloading
    recordings into somebody's plain Canvas folder."""
    assert S.infer_contract_from_manifest(None) is None
    assert S.infer_contract_from_manifest({}) is None


def test_a_manifest_with_no_recognised_kinds_infers_nothing():
    assert S.infer_contract_from_manifest({"v1": {"weird": "x.bin"}}) is None
    assert S.infer_contract_from_manifest({"v1": {}}) is None


def test_the_kinds_on_disk_become_the_outputs():
    c = S.infer_contract_from_manifest({"v1": {"mp3": "a.mp3", "txt": "a.txt"}})
    assert c["output_mp3"] is True and c["output_txt"] is True
    assert c["output_mp4"] is False and c["output_srt"] is False


def test_kinds_are_unioned_across_recordings():
    """Different recordings can have different artifacts (a failed transcript,
    a video-only session). The contract is what the user ASKED for, so it is
    the union rather than the intersection."""
    c = S.infer_contract_from_manifest({
        "v1": {"mp3": "a.mp3"},
        "v2": {"srt": "b.srt"},
    })
    assert c["output_mp3"] is True and c["output_srt"] is True


def test_a_recordings_subfolder_implies_the_separate_layout():
    c = S.infer_contract_from_manifest(
        {"v1": {"mp3": "Panopto Recordings/Lecture 1/a.mp3"}})
    assert c["layout"] == "separate"


def test_layout_detection_handles_windows_separators_and_case():
    """The stored path comes from whichever OS wrote it."""
    for rel in ["Panopto Recordings\\L1\\a.mp3",
                "panopto recordings/l1/a.mp3",
                "Module 3/PANOPTO RECORDINGS/a.mp3"]:
        assert S.infer_contract_from_manifest({"v1": {"mp3": rel}})["layout"] \
            == "separate", rel


def test_files_beside_the_course_content_imply_the_match_layout():
    c = S.infer_contract_from_manifest({"v1": {"mp3": "Module 1/lecture.mp3"}})
    assert c["layout"] == "match"


def test_a_malformed_manifest_entry_is_skipped_not_fatal():
    """This runs during sync analysis; a stray value must not abort the run."""
    c = S.infer_contract_from_manifest({
        "v1": "not a dict",
        "v2": None,
        "v3": {"mp3": "ok.mp3"},
    })
    assert c is not None and c["output_mp3"] is True


def test_a_non_string_path_does_not_break_layout_detection():
    c = S.infer_contract_from_manifest({"v1": {"mp3": 12345}})
    assert c is not None and c["layout"] == "match"


def test_an_inferred_contract_is_enabled():
    """The whole point of the recovery: the next sync must actually run the
    Panopto pass again."""
    c = S.infer_contract_from_manifest({"v1": {"txt": "a.txt"}})
    assert S.is_enabled(c) is True


def test_an_inferred_contract_has_the_full_contract_shape():
    c = S.infer_contract_from_manifest({"v1": {"mp3": "a.mp3"}})
    assert set(c) == {"output_mp4", "output_mp3", "output_txt", "output_srt",
                      "layout"}


def test_inference_asserts_only_what_the_artifacts_show():
    """A transcript proves the audio step ran, but the user may have turned mp3
    output off since. Inferring mp3 from a txt would resurrect a format they
    deliberately disabled."""
    c = S.infer_contract_from_manifest({"v1": {"txt": "a.txt"}})
    assert c["output_txt"] is True
    assert c["output_mp3"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Contract -> UI keys
# ═══════════════════════════════════════════════════════════════════════════

def test_contract_maps_onto_the_badge_key_names():
    ui = S.contract_to_ui_keys(S.make_contract(
        mp4=True, mp3=False, txt=True, srt=False, layout="separate"))
    assert ui["pan_out_mp4"] is True
    assert ui["pan_out_mp3"] is False
    assert ui["pan_out_txt"] is True
    assert ui["pan_out_srt"] is False
    assert ui["pan_layout"] == "separate"


@pytest.mark.parametrize("contract", [None, {}])
def test_an_absent_contract_maps_to_all_off(contract):
    ui = S.contract_to_ui_keys(contract)
    assert ui["pan_layout"] == "match"
    assert not any(ui[k] for k in
                   ("pan_out_mp4", "pan_out_mp3", "pan_out_txt", "pan_out_srt"))
