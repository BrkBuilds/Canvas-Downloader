"""Tests for the design-token palette and the Rule 8 palette-drift check.

Rule 8 fails the build when a hex lands within 1.0 CIEDE2000 of a token, so its
colour maths has to be right - a wrong CIEDE2000 would either wave real drift
through or block legitimate colours. These pin the formula against published
reference values and guard the palette's own invariants.
"""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_architecture", ROOT / "scripts" / "verify_architecture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


va = _load_verifier()


# --------------------------------------------------------------------------
# CIEDE2000 correctness
# --------------------------------------------------------------------------

def _de(hex_a: str, hex_b: str) -> float:
    return va._ciede2000(va._hex_to_lab(hex_a), va._hex_to_lab(hex_b))


def test_identical_colours_have_zero_distance():
    assert _de("#4da8da", "#4da8da") == pytest.approx(0.0, abs=1e-9)


def test_distance_is_symmetric():
    assert _de("#0d1117", "#11141a") == pytest.approx(_de("#11141a", "#0d1117"), abs=1e-9)


def test_black_to_white_is_a_large_distance():
    # The extreme case: must be ~100 (pure lightness difference).
    assert _de("#000000", "#ffffff") == pytest.approx(100.0, abs=0.5)


@pytest.mark.parametrize("lab1,lab2,expected", [
    # Canonical CIEDE2000 test vectors (Sharma, Wu & Dalal 2005). Fed straight
    # to the formula in Lab so nothing is lost to 8-bit sRGB quantisation.
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    # This pair straddles the hue discontinuity and is the case naive
    # implementations get wrong - it exercises the Rt rotation term.
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
])
def test_ciede2000_matches_published_reference_vectors(lab1, lab2, expected):
    assert va._ciede2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)


def test_measured_palette_distances():
    """The two merges Rule 8 was built to catch, pinned at their real values."""
    assert _de("#0d1117", "#0e1117") == pytest.approx(0.47, abs=0.02)
    assert _de("#2d3248", "#2d3148") == pytest.approx(0.80, abs=0.02)


def test_hex_shorthand_expands():
    assert va._hex_norm("#ABC") == "#aabbcc"
    assert va._hex_norm("666") == "#666666"
    # A 3-digit and its 6-digit form are the same colour, so distance is 0.
    assert _de(va._hex_norm("#666"), "#666666") == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# Palette invariants
# --------------------------------------------------------------------------

def _tokens() -> dict[str, str]:
    import sys
    sys.path.insert(0, str(ROOT))
    from shared import theme
    return {k: v for k, v in vars(theme).items()
            if k.isupper() and isinstance(v, str) and v.startswith("#")}


def test_every_token_is_a_full_six_digit_lowercase_hex():
    """Mixed formats (#666 vs #666666, #FFF vs #fff) are what makes a palette
    hard to grep and easy to duplicate accidentally."""
    for name, value in _tokens().items():
        assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{name} = {value!r}"


def test_no_two_distinct_token_names_are_accidental_near_duplicates():
    """Two tokens may share a value deliberately (an alias, or a border that
    tracks a surface colour), but they must never be merely CLOSE - that is the
    same invisible drift Rule 8 exists to stop, just inside the palette itself.
    """
    toks = list(_tokens().items())
    for i, (n1, v1) in enumerate(toks):
        for n2, v2 in toks[i + 1:]:
            if v1 == v2:
                continue          # exact aliases are intentional
            d = _de(v1, v2)
            assert d > va._COLOUR_TOLERANCE, (
                f"{n1} ({v1}) and {n2} ({v2}) are {d:.2f} apart - "
                f"indistinguishable, so one of them should be dropped")


def test_rule8_flags_a_near_duplicate_and_names_the_token():
    src = "a { color: #0e1117; }"
    hits = va.check_near_duplicate_colours(src, Path("fake.css"), set())
    assert len(hits) == 1
    assert "BG_TERMINAL" in hits[0].message


def test_rule8_accepts_the_token_itself():
    src = "a { color: #0d1117; }"
    assert va.check_near_duplicate_colours(src, Path("fake.css"), set()) == []


def test_rule8_ignores_a_hex_quoted_in_a_comment():
    """Documenting a ramp must not trip the rule that polices the ramp."""
    src = "/* Level 3 (body): darkest -> #0e1117 */\na { color: #0d1117; }"
    assert va.check_near_duplicate_colours(src, Path("fake.css"), set()) == []


def test_rule8_leaves_genuinely_distinct_colours_alone():
    src = "a { color: #b89dfe; background: #f97316; border-color: #68d4a3; }"
    assert va.check_near_duplicate_colours(src, Path("fake.css"), set()) == []
