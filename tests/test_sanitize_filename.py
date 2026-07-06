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
