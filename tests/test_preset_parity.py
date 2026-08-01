"""The two built-in preset lists must stay identical.

There are TWO definitions of the same five presets, on two different entry
points:

* ``ui/quick_download.py:_QUICK_PRESETS`` - the Quick Download preset picker.
* ``core/preset_manager.py:_BUILTIN_PRESETS`` - the same five offered from the
  Presets Hub on the Custom Download page.

``_BUILTIN_PRESETS`` says in its own comment that it *"mirrors the Quick
Download presets exactly so both entry points offer the same configurations"* -
but nothing enforced it, and they drifted. Measured 2026-07-31: **Files Only**
carried ``pan_out_mp4: True`` in the manager and ``False`` in Quick Download, so
the same named preset downloaded multi-GB lecture videos from one screen and not
from the other. That is invisible in review (the two lists are ~90 lines apart
in different files) and invisible at runtime until a user watches a "files only"
download fetch 4 GB of video.

The parity is on ``settings`` only. The *display* strings deliberately differ -
the hub shows a long description, the picker shows a one-line blurb.
"""

from __future__ import annotations

import pytest

from core.preset_manager import PresetManager
from ui.quick_download import _QUICK_PRESETS


def _pairs():
    """(name, quick_settings, builtin_settings) for each preset, in order."""
    builtins = PresetManager("").get_builtin_presets()
    assert len(builtins) == len(_QUICK_PRESETS), (
        f"{len(_QUICK_PRESETS)} Quick Download presets vs {len(builtins)} "
        "built-ins - one entry point offers a preset the other does not."
    )
    return [
        (q['name'], q['settings'], b['settings'])
        for q, b in zip(_QUICK_PRESETS, builtins)
    ]


@pytest.mark.parametrize("name, quick, builtin", _pairs(),
                         ids=[p[0] for p in _pairs()])
def test_the_two_preset_lists_agree(name, quick, builtin):
    assert quick.keys() == builtin.keys(), (
        f"{name}: the two definitions configure different keys"
    )
    differing = {k: (quick[k], builtin[k]) for k in quick if quick[k] != builtin[k]}
    assert not differing, (
        f"{name} differs between ui/quick_download.py and core/preset_manager.py: "
        + ", ".join(f"{k} is {q!r} vs {b!r}" for k, (q, b) in differing.items())
    )


def test_files_only_pulls_no_recordings():
    """The specific drift that shipped, asserted on its own.

    "Files Only" promises the teacher's uploaded files and nothing else. A
    lecture recording is a separate, opt-in content type - and by far the
    largest thing the app can download - so neither definition may enable one.
    """
    quick = next(p for p in _QUICK_PRESETS if p['name'] == 'Files Only')
    builtin = next(p for p in PresetManager("").get_builtin_presets()
                   if p['preset_name'] == 'Files Only')
    for label, settings in (("Quick Download", quick['settings']),
                            ("Presets Hub", builtin['settings'])):
        for key in ('pan_out_mp4', 'pan_out_mp3', 'pan_out_txt', 'pan_out_srt'):
            assert settings[key] is False, f"{label}'s Files Only enables {key}"


def test_slides_and_pdfs_pulls_no_recordings():
    """Same promise, same reason - the other 'just the essentials' preset."""
    quick = next(p for p in _QUICK_PRESETS if p['name'] == 'Slides & PDFs Only')
    for key in ('pan_out_mp4', 'pan_out_mp3', 'pan_out_txt', 'pan_out_srt'):
        assert quick['settings'][key] is False
