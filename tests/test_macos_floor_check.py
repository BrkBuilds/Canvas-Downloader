"""The macOS floor guard must not fail CONFIDENTLY.

`scripts/check_macos_floor.py` fails the macOS build when a bundled binary needs
a newer macOS than `LSMinimumSystemVersion` promises. It was added on
2026-08-14, wired straight into `.github/workflows/build-macos.yml`, and had
NO test and no successful CI run behind it - the last green macOS build was
2026-07-11. The first time it ever executed was 2026-08-22, where it failed the
v2.0.2 build claiming the bundle "requires macOS 1267.0".

1267.0 is ld64's version. `LC_BUILD_VERSION` carries the linker's version in a
field literally named `version`, four lines below the `minos` this is meant to
read, so a line-wise `minos|version` regex matched it on every modern binary -
214 of 215 in that build. The floor had not moved at all; the parser had never
been run.

Same family as the lesson in CLAUDE.md about a test skipped on your own
platform: a guard that has not run somewhere you can see it is not protection,
and this one was worse than absent, because it blocked a release while being
wrong. These tests are deliberately platform-independent - pure text for the
parser, an injected reader for the decision - so they run on every machine
rather than only on the one that can produce a Mach-O.
"""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.check_macos_floor import main, parse_minos  # noqa: E402

# Captured verbatim from `otool -l` on macOS 26.6.1 against
# UserNotifications/_UserNotifications.cpython-311-darwin.so - the exact binary
# the failing CI run named. Two slices: an x86_64 one carrying the old
# LC_VERSION_MIN_MACOSX, an arm64 one carrying LC_BUILD_VERSION.
REAL_FAT_BINARY = """\
Load command 6
     cmd LC_UUID
 cmdsize 24
    uuid 2D95F40F-E1C4-3B13-AC5F-540B62E4A8E3
Load command 7
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.9
      sdk 26.5
Load command 8
      cmd LC_SOURCE_VERSION
  cmdsize 16
  version 0.0
Load command 9
          cmd LC_LOAD_DYLIB
      cmdsize 56
         name /usr/lib/libSystem.B.dylib (offset 24)
   time stamp 2 Thu Jan  1 01:00:02 1970
      current version 1356.0.0
compatibility version 1.0.0
Load command 8
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 11.0
      sdk 26.5
   ntools 1
     tool 3
  version 1267.0
Load command 9
      cmd LC_SOURCE_VERSION
  cmdsize 16
  version 0.0
"""


# --------------------------------------------------------------- the parser

def test_the_linker_version_inside_lc_build_version_is_not_a_macos_floor():
    """THE regression test. `version 1267.0` sits inside LC_BUILD_VERSION,
    below `tool 3` (TOOL_LD). Reading it as a floor is what blocked v2.0.2."""
    assert parse_minos(REAL_FAT_BINARY) == "11.0"


def test_the_old_lc_version_min_macosx_command_is_still_read():
    """Not every wheel is built with LC_BUILD_VERSION - the x86_64 slice above
    uses the pre-10.14 command, where the floor really IS spelled `version`."""
    only_old = """\
Load command 7
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.9
      sdk 26.5
"""
    assert parse_minos(only_old) == "10.9"


def test_the_highest_slice_wins_because_every_slice_has_to_load():
    two_slices = """\
      cmd LC_BUILD_VERSION
 platform 1
    minos 11.0
      cmd LC_BUILD_VERSION
 platform 1
    minos 14.0
"""
    assert parse_minos(two_slices) == "14.0"


def test_lc_source_version_is_ignored():
    """LC_SOURCE_VERSION's field is also called `version`. It is a project
    version, not an OS, and it is usually 0.0 - which would go unnoticed,
    which is exactly why it needs pinning rather than trusting."""
    src_only = """\
      cmd LC_SOURCE_VERSION
  cmdsize 16
  version 93.7
"""
    assert parse_minos(src_only) is None


def test_a_load_dylib_current_version_is_ignored():
    """`current version 1356.0.0` is a dylib's own version. It is in the
    thousands, so reading it would fail the build on every binary that links
    libSystem - i.e. all of them."""
    assert parse_minos(REAL_FAT_BINARY.split("Load command 8\n      cmd LC_BUILD")[0]) == "10.9"


def test_a_non_macos_platform_is_not_read_as_a_macos_floor():
    """PLATFORM_MACOS is 1. A MACCATALYST (6) or iOS build numbers its OS on a
    different scale entirely, so its minos says nothing about macOS."""
    catalyst = """\
      cmd LC_BUILD_VERSION
 platform 6
    minos 18.0
      sdk 18.0
"""
    assert parse_minos(catalyst) is None


def test_a_spelled_out_macos_platform_is_accepted():
    """Newer otool may print the name rather than the number. Rejecting it
    would silently stop reading real floors."""
    named = """\
      cmd LC_BUILD_VERSION
 platform MACOS
    minos 15.0
"""
    assert parse_minos(named) == "15.0"


def test_cmdsize_is_not_mistaken_for_a_cmd_line():
    """`cmdsize` starts with `cmd`. If it were treated as a command boundary
    the parser would lose track of which command it is inside."""
    assert parse_minos(REAL_FAT_BINARY) == "11.0"


def test_no_version_commands_at_all_returns_none():
    assert parse_minos("Load command 0\n     cmd LC_UUID\n cmdsize 24\n") is None


def test_empty_output_returns_none():
    assert parse_minos("") is None


# ------------------------------------------------- the pass/fail decision
#
# The parser being right is not the same as the comparison firing. A test that
# only covered parse_minos would pass against a main() whose check never runs.

def _fake_bundle(tmp_path: Path, declared: str, n_binaries: int = 2) -> Path:
    app = tmp_path / "Fake.app"
    (app / "Contents").mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump({"LSMinimumSystemVersion": declared}, fh)
    macos = app / "Contents" / "MacOS"
    macos.mkdir()
    for i in range(n_binaries):
        # Real 64-bit little-endian Mach-O magic, so _is_macho accepts it on
        # any platform without needing a compiler.
        (macos / f"bin{i}").write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 32)
    return app


def test_a_binary_above_the_declared_floor_fails_the_build(tmp_path):
    app = _fake_bundle(tmp_path, "14.0")
    rc = main(["prog", str(app)], minos_reader=lambda p: "15.0")
    assert rc == 1


def test_a_binary_at_or_below_the_declared_floor_passes(tmp_path):
    app = _fake_bundle(tmp_path, "14.0")
    assert main(["prog", str(app)], minos_reader=lambda p: "11.0") == 0
    assert main(["prog", str(app)], minos_reader=lambda p: "14.0") == 0


def test_the_real_bundle_shape_would_now_pass(tmp_path):
    """End to end on the numbers from the failing run: the binary CI blamed
    parses as 11.0, and 11.0 against a declared 14.0 is a pass. This is the
    control that says the v2.0.2 build was blocked by the parser and not by a
    genuine floor rise."""
    app = _fake_bundle(tmp_path, "14.0")
    assert main(["prog", str(app)],
                minos_reader=lambda p: parse_minos(REAL_FAT_BINARY)) == 0


def test_an_implausible_parse_refuses_to_decide_rather_than_failing_the_build(tmp_path):
    """The failure that shipped. A four-digit 'macOS version' is a parse bug,
    and the guard must say so instead of blocking a release with a confident
    wrong number. Exit 2 is 'could not inspect', distinct from 1 'floor
    violated'."""
    app = _fake_bundle(tmp_path, "14.0")
    assert main(["prog", str(app)], minos_reader=lambda p: "1267.0") == 2


def test_a_bundle_with_no_minimum_declared_is_an_error(tmp_path):
    app = tmp_path / "Fake.app"
    (app / "Contents").mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump({"CFBundleName": "x"}, fh)
    assert main(["prog", str(app)], minos_reader=lambda p: "11.0") == 1


def test_a_path_that_is_not_a_bundle_is_an_error(tmp_path):
    assert main(["prog", str(tmp_path / "nope.app")],
                minos_reader=lambda p: "11.0") == 2


def test_main_reads_its_argv_argument_and_not_sys_argv(tmp_path):
    """A CLI entry point that reads sys.argv implicitly cannot be called
    in-process, and the first caller is always a test. Under pytest sys.argv
    holds the runner's flags, so this would die on '-q' with SystemExit(2)."""
    app = _fake_bundle(tmp_path, "14.0")
    assert main(["prog", str(app)], minos_reader=lambda p: "11.0") == 0
