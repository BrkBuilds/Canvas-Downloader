"""Tests for CanvasManager._sanitize_filename - the single gate between
Canvas-supplied names and the local filesystem.

Every downloaded file's on-disk name passes through this function, so it is
the defence against path traversal, Windows reserved device names, dangerous
Unicode, and over-long names. A regression here corrupts user folders or
crashes downloads on Windows.

The method only touches ``self`` for nothing at all (it is effectively
static), so we instantiate via ``__new__`` to avoid the constructor's
API-client setup.
"""

from __future__ import annotations

import pytest

from core.canvas_logic import CanvasManager


@pytest.fixture(scope="module")
def sanitize():
    cm = CanvasManager.__new__(CanvasManager)
    return cm._sanitize_filename


# ── Path traversal & separators ──────────────────────────────────────────────

def test_strips_forward_slash_traversal(sanitize):
    out = sanitize("../../etc/passwd")
    assert "/" not in out and "\\" not in out
    assert ".." not in out.split(".")[0] or not out.startswith(".")


def test_strips_backslash_traversal(sanitize):
    out = sanitize(r"..\..\windows\system32\evil.dll")
    assert "/" not in out and "\\" not in out


def test_never_returns_leading_dot_underscore_junk(sanitize):
    # lstrip(' _') / rstrip('. _') behaviour: no leading/trailing separators
    out = sanitize("  _  spaced name . ")
    assert out == out.strip(" _").rstrip(". _") or out == "untitled"
    assert not out.startswith((" ", "_"))
    assert not out.endswith((" ", ".", "_"))


# ── Windows reserved device names ────────────────────────────────────────────

@pytest.mark.parametrize("name", ["CON.pdf", "con.txt", "PRN.docx", "AUX", "NUL.zip"])
def test_reserved_device_names_are_prefixed(sanitize, name):
    out = sanitize(name)
    assert out.startswith("_"), f"{name!r} -> {out!r} would crash file creation on Windows"


@pytest.mark.parametrize("name", ["COM1.txt", "com9.pdf", "LPT3", "lpt1.csv"])
def test_reserved_com_lpt_names_are_prefixed(sanitize, name):
    out = sanitize(name)
    assert out.startswith("_")


def test_non_reserved_similar_names_untouched(sanitize):
    # CONF, COM10, LPTX are NOT reserved and must not be mangled
    assert sanitize("CONF.pdf") == "CONF.pdf"
    assert sanitize("COMMON.txt") == "COMMON.txt"


# ── Illegal filesystem characters ────────────────────────────────────────────

def test_windows_illegal_chars_removed(sanitize):
    out = sanitize('a<b>c:d"e|f?g*h.pdf')
    for ch in '<>:"|?*':
        assert ch not in out
    assert out.endswith(".pdf")


def test_control_chars_removed(sanitize):
    out = sanitize("bad\x00name\x1f.txt")
    assert out == "badname.txt"


# ── Dangerous Unicode ────────────────────────────────────────────────────────

def test_bidi_override_stripped(sanitize):
    # U+202E right-to-left override - classic "invoice_‮fdp.exe" spoof
    out = sanitize("invoice_‮fdp.exe")
    assert "‮" not in out


def test_zero_width_chars_stripped(sanitize):
    out = sanitize("he​llo‍.pdf")
    assert out == "hello.pdf"


# ── URL decoding ─────────────────────────────────────────────────────────────

def test_percent_encoding_decoded(sanitize):
    assert sanitize("My%20File.pdf") == "My File.pdf"


def test_plus_decoded_as_space(sanitize):
    # unquote_plus semantics (Canvas form-encodes some filenames)
    assert sanitize("Week+1+Slides.pptx") == "Week 1 Slides.pptx"


# ── Length capping ───────────────────────────────────────────────────────────

def test_long_name_capped_with_extension_preserved(sanitize):
    out = sanitize("a" * 300 + ".pdf")
    assert len(out) <= 120
    assert out.endswith(".pdf")


def test_long_name_without_meaningful_ext_hard_capped(sanitize):
    out = sanitize("b" * 300)
    assert len(out) <= 120


# ── Degenerate inputs ────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", None, "???", '""', "\x00\x01"])
def test_degenerate_inputs_yield_untitled(sanitize, bad):
    assert sanitize(bad) == "untitled"


def test_plain_name_passes_through(sanitize):
    assert sanitize("Lecture 3 - Dynamics.pdf") == "Lecture 3 - Dynamics.pdf"


# ── The length cap is in CHARACTERS; the filesystem limit is in UTF-16 UNITS ──
#
# Measured on APFS, macOS 26.6.1 (2026-08-20), by writing real files: a
# component may hold at most **255 UTF-16 code units**. Not bytes and not Python
# characters - both readings are wrong, and the repo carried one of each:
#
#     255 x "a"      255 units,  255 bytes  -> OK
#     255 x "ae"     255 units,  510 bytes  -> OK      (so not a byte limit)
#     127 x emoji    254 units,  508 bytes  -> OK
#     128 x emoji    256 units,  512 bytes  -> ENAMETOOLONG
#     253 x "ae" + 1 emoji   255 units      -> OK
#     254 x "ae" + 1 emoji   256 units      -> ENAMETOOLONG
#
# An astral character (emoji, rarer CJK extensions, older historic scripts) is a
# SURROGATE PAIR - two units for one Python character - so the ratio between the
# cap and the limit is 2:1 in the worst case. NTFS counts UTF-16 units too, so
# this is not a macOS quirk to guard on one platform.
#
# Today the margin is comfortable but not obvious: 120 characters of emoji is
# 240 units, measured at 236 with the suffix inside the cap, against a ceiling of
# 255. Raising max_length to anything over 127 would make an all-astral Canvas
# filename illegal on both platforms - and it would fail as ENAMETOOLONG at
# download time, i.e. as a missing file, which is the direction this repo's
# conventions treat as unrecoverable.

_UTF16_COMPONENT_LIMIT = 255


def _utf16_units(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def test_the_default_cap_cannot_exceed_the_filesystem_component_limit():
    """The cap counts characters; the filesystem counts UTF-16 units."""
    import inspect
    default = inspect.signature(CanvasManager._sanitize_filename) \
        .parameters["max_length"].default
    worst_case_units = default * 2          # every character an astral pair
    assert worst_case_units <= _UTF16_COMPONENT_LIMIT, (
        f"max_length={default} characters can produce {worst_case_units} UTF-16 "
        f"units, over the {_UTF16_COMPONENT_LIMIT}-unit component limit on both "
        f"APFS and NTFS. An all-emoji Canvas filename would then fail as "
        f"ENAMETOOLONG at download time - a missing file, not a visible error. "
        f"Cap out at {_UTF16_COMPONENT_LIMIT // 2} characters.")


@pytest.mark.parametrize("label,ch", [
    ("emoji (surrogate pair)", "\U0001F600"),
    ("astral CJK extension B", "\U00020000"),
    ("Danish ae-ligature", "æ"),
    ("BMP CJK", "漢"),
    ("ascii", "L"),
])
def test_no_input_makes_the_sanitiser_emit_an_illegal_component(sanitize, label, ch):
    out = sanitize(ch * 400 + ".pdf")
    assert _utf16_units(out) <= _UTF16_COMPONENT_LIMIT, (
        f"{label}: sanitised to {_utf16_units(out)} UTF-16 units, which no "
        f"filesystem this app targets will accept")


def test_an_explicit_max_length_is_also_bound_by_the_unit_limit(sanitize):
    """Callers may pass max_length; the same arithmetic applies to them."""
    out = sanitize("\U0001F600" * 400 + ".pdf", max_length=127)
    assert _utf16_units(out) <= _UTF16_COMPONENT_LIMIT
