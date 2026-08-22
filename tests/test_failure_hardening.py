"""Regression guards for the 2026-08-06 crash/data-loss audit.

Every test here corresponds to a defect that was REPRODUCED against the real
code, not to a hypothetical. They are grouped by the thing that was at risk,
because that is what makes a failure here readable: if one goes red, the
question to ask is "what did the user just lose", not "which function changed".

The through-line is a single rule the audit kept finding broken:

    Never destroy data on the strength of an error you have not identified.

A transient failure and a permanent one are indistinguishable at the type level
in both of this app's stores - ``sqlite3.OperationalError`` IS a
``sqlite3.DatabaseError``, and ``UnicodeDecodeError`` is NOT a
``json.JSONDecodeError`` - so both stores were recovering from problems they did
not actually have, by throwing away files that were perfectly intact.
"""

from __future__ import annotations

import gc
import importlib
import io
import json
import os
import sqlite3
import subprocess
import threading

import pytest


# ═══════════════════════════════════════════════════════════════════════
#  make_long_path - the \\?\ prefix must produce a path the KERNEL accepts
# ═══════════════════════════════════════════════════════════════════════

class TestMakeLongPath:
    """``\\\\?\\`` turns OFF Win32 path parsing, so what it is handed must
    already be canonical. Two shapes were being emitted that the kernel rejects
    outright, and both were reachable from the UI."""

    @staticmethod
    def _mlp():
        from shared.helpers import make_long_path
        return make_long_path

    @pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
    def test_unc_uses_the_UNC_prefix_form(self):
        # \\server\share -> \\?\UNC\server\share, NOT \\?\\\server\share.
        # The broken form fails with WinError 123 (syntax incorrect) on every
        # open/stat/sqlite-connect, so a user syncing to a network share could
        # not write a single file.
        got = self._mlp()("\\\\srv\\share\\Courses\\f.txt")
        assert got == "\\\\?\\UNC\\srv\\share\\Courses\\f.txt"

    @pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
    def test_unc_result_is_syntactically_valid_to_the_os(self):
        """The point is not the string, it is that Windows accepts it.

        Asserted by error KIND against a host that certainly does not exist:
        a malformed prefix gives WinError 123 ("syntax is incorrect"), a
        well-formed one gets far enough to report WinError 53 ("network path
        not found"). Anything other than 123 means the syntax was accepted.

        The probe hostname must contain NO UNDERSCORE. An underscore is illegal
        in a hostname, so Windows rejects the path on syntax grounds - with the
        very WinError 123 this test reads as failure - before it ever looks for
        the host. Using "nosuchhost_zz" here failed against the CORRECT
        implementation and looked exactly like the bug it guards.
        """
        p = self._mlp()("\\\\nosuchhostzz\\share\\x.txt")
        try:
            os.stat(p)
        except OSError as e:
            assert getattr(e, "winerror", None) != 123, (
                f"kernel rejected the path syntax: {p!r}")

    @pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
    def test_forward_slashes_are_normalised(self):
        # \\?\C:/x does not resolve AT ALL - exists() returns False and open()
        # raises "No such file or directory", so the file looks absent rather
        # than erroring. Tk's askdirectory (the fallback folder picker) returns
        # forward slashes on Windows, which is how this reached real users.
        assert self._mlp()("C:/Users/x/f.txt") == "\\\\?\\C:\\Users\\x\\f.txt"
        assert self._mlp()("C:/Users\\x/f.txt") == "\\\\?\\C:\\Users\\x\\f.txt"

    @pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
    def test_a_real_file_is_reachable_through_either_spelling(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hi", encoding="utf-8")
        for spelling in (str(f), str(f).replace("\\", "/")):
            lp = self._mlp()(spelling)
            assert os.path.exists(lp), f"unreachable via {spelling!r}"
            with open(lp, encoding="utf-8") as fh:
                assert fh.read() == "hi"

    @pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
    def test_dot_segments_are_resolved(self):
        # The prefix disables normalisation, so ".." would be taken as a
        # literal directory name.
        assert self._mlp()("C:\\a\\b\\..\\c\\.\\f.txt") == "\\\\?\\C:\\a\\c\\f.txt"

    @pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
    @pytest.mark.parametrize("already", [
        "\\\\?\\C:\\a.txt",                 # extended-length
        "\\\\?\\UNC\\srv\\share\\f",        # extended-length UNC
        "\\\\.\\pipe\\x",                   # Win32 device path
    ])
    def test_prefixed_and_device_paths_are_left_alone(self, already):
        assert self._mlp()(already) == already

    @pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
    @pytest.mark.parametrize("rel", ["rel\\p.txt", "p.txt", "\\Users\\x"])
    def test_non_absolute_paths_are_untouched(self, rel):
        # "\Users\x" is drive-RELATIVE: it has no drive letter, so it cannot be
        # expressed as an extended-length path at all. Widening the gate to
        # ntpath.isabs() would emit the invalid "\\?\\Users\x".
        assert self._mlp()(rel) == rel

    def test_non_windows_is_a_passthrough(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        assert self._mlp()("/home/x/f.txt") == "/home/x/f.txt"

    def test_there_is_exactly_ONE_implementation(self):
        """``core.sync_manager`` carried its own COPY of this function, and all
        26 manifest call sites used that copy - so fixing the shared one did not
        reach the sync database at all. The duplicate is now a thin alias; if a
        second real implementation ever reappears, a path fix will again apply
        to only half the app, silently.
        """
        import core.sync_manager as sm
        from shared.helpers import make_long_path as shared
        for probe in ("\\\\srv\\share\\f.txt", "C:/Users/x/f.txt",
                      "C:\\a\\b\\..\\c.txt", "rel\\p.txt"):
            assert sm.make_long_path(probe) == shared(probe), (
                f"core.sync_manager.make_long_path disagrees on {probe!r} - "
                "it is a second implementation again")

    def test_nothing_hand_rolls_the_prefix(self):
        """A literal '\\\\?\\' + path concatenation is the bug itself: it cannot
        produce the UNC form and does not normalise separators."""
        from pathlib import Path as _P
        import re
        root = _P(__file__).resolve().parent.parent
        offenders = []
        pattern = re.compile(r"""['"]\\\\\\\\\?\\\\['"]\s*\+""")
        # The ONE legitimate concatenation is the helper's own return statement.
        # Raw string: this must match the characters in the FILE, and a normal
        # literal halves every backslash and silently never matches.
        allowed = r"""return '\\\\?\\' + norm"""
        for pkg in ("core", "converters", "shared", "panopto", "sync", "engine", "ui"):
            for f in (root / pkg).rglob("*.py"):
                for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                    if pattern.search(line) and allowed not in line:
                        offenders.append(f"{f.relative_to(root)}:{i}: {line.strip()}")
        assert not offenders, (
            "hand-rolled long-path prefix (use shared.helpers.make_long_path):\n"
            + "\n".join(offenders))


# ═══════════════════════════════════════════════════════════════════════
#  SyncManager - a transient error must never cost the manifest
# ═══════════════════════════════════════════════════════════════════════

def _close_handles():
    """sqlite connections are closed by refcount; force it before asserting on
    files, or Windows will refuse the rename/unlink under test for the WRONG
    reason and the test will pass by accident."""
    gc.collect()


def _clobber(path, payload: bytes):
    """Overwrite a file the app has marked HIDDEN (Windows refuses 'wb')."""
    if os.path.exists(path) and os.name == "nt":
        subprocess.run(["attrib", "-H", str(path)], capture_output=True)
    with open(path, "wb") as f:
        f.write(payload)


def _seed_manifest(folder, course_id=4242):
    from core.sync_manager import SyncManager
    sm = SyncManager(str(folder), course_id=course_id, course_name="Macro")
    m = sm.load_manifest()
    m["files"]["999"] = {
        "canvas_file_id": 999, "canvas_filename": "lecture.pdf",
        "local_path": "lecture.pdf", "canvas_updated_at": "2026-01-01",
        "downloaded_at": "2026-01-01", "original_size": 10,
        "is_ignored": False, "original_md5": "abc", "content_sig": "",
    }
    sm.save_manifest(m)
    del sm
    _close_handles()


class TestManifestSurvivesTransientErrors:
    """``.canvas_sync.db`` is the folder's ONLY record of what has been synced.
    Losing it does not merely reset a preference - it makes every local file
    untracked, so the next sync re-downloads over the student's annotated
    copies, and ``_NewVersion`` protection (which reads manifest rows) cannot
    fire because there are no rows."""

    @pytest.mark.parametrize("message", [
        "unable to open database file",      # share offline / disk full / bad path
        "database is locked",                # other process / antivirus / stuck WAL
        "attempt to write a readonly database",  # read-only attribute or ACL
    ])
    def test_transient_operational_errors_leave_the_db_untouched(
            self, tmp_path, monkeypatch, message):
        from core.sync_manager import SyncManager
        _seed_manifest(tmp_path)
        db = tmp_path / ".canvas_sync.db"
        before = db.read_bytes()

        # Every one of these is an OperationalError, which IS a DatabaseError -
        # which is exactly why the old handler mistook them for corruption.
        assert issubclass(sqlite3.OperationalError, sqlite3.DatabaseError)

        def boom(*a, **k):
            raise sqlite3.OperationalError(message)
        monkeypatch.setattr(sqlite3, "connect", boom)
        sm = SyncManager(str(tmp_path), course_id=4242, course_name="Macro")
        monkeypatch.undo()

        assert db.exists(), f"{message!r} destroyed the manifest"
        assert db.read_bytes() == before, f"{message!r} altered the manifest"
        assert not list(tmp_path.glob(".canvas_sync_corrupted*")), \
            "a transient error must not quarantine anything"
        assert sm._db_init_failed is True, "the failure must be reported"
        assert sm.db_was_reset is False, "nothing was reset, so do not claim it"

    def test_repeated_transient_failure_never_erases_the_backup(self, tmp_path, monkeypatch):
        """The compounding bug: attempt 0 renamed the DB aside, then attempt 1
        UNLINKED that very backup before failing to rename again - so two
        rounds of a transient error left the folder with neither."""
        from core.sync_manager import SyncManager
        _seed_manifest(tmp_path)
        db = tmp_path / ".canvas_sync.db"
        before = db.read_bytes()

        def boom(*a, **k):
            raise sqlite3.OperationalError("unable to open database file")
        monkeypatch.setattr(sqlite3, "connect", boom)
        for _ in range(3):
            SyncManager(str(tmp_path), course_id=4242, course_name="Macro")
        monkeypatch.undo()

        assert db.exists() and db.read_bytes() == before
        assert [p.name for p in tmp_path.iterdir()] != [], "folder was emptied"

    def test_folder_that_cannot_be_created_is_flagged_not_raised(self, tmp_path, monkeypatch):
        """mkdir sits above the try: in _init_db_locked, so an unreachable
        folder surfaced as a raw traceback on the sync page."""
        from core.sync_manager import SyncManager
        import pathlib

        def no_mkdir(self, *a, **k):
            raise OSError(1, "network path is unavailable")
        monkeypatch.setattr(pathlib.Path, "mkdir", no_mkdir)
        sm = SyncManager(str(tmp_path / "gone"), course_id=1, course_name="X")
        assert sm._db_init_failed is True


class TestGenuineCorruptionStillRecovers:
    """The fix must not buy safety by disabling recovery."""

    def test_a_non_database_file_is_quarantined_and_replaced(self, tmp_path):
        from core.sync_manager import SyncManager
        db = tmp_path / ".canvas_sync.db"
        _clobber(db, b"NOT A SQLITE FILE " * 200)
        sm = SyncManager(str(tmp_path), course_id=7, course_name="Micro")
        assert sm.db_was_reset is True
        assert sm._db_init_failed is False
        assert (tmp_path / ".canvas_sync_corrupted.db").exists()
        assert sm.load_manifest()["course_id"] == 7   # fresh DB is usable

    def test_a_second_corruption_keeps_the_first_backup(self, tmp_path):
        """The EARLIEST backup is the valuable one - it is the copy closest to
        the last good sync. It used to be unlinked to make room."""
        from core.sync_manager import SyncManager
        db = tmp_path / ".canvas_sync.db"
        _clobber(db, b"NOT SQLITE " * 200)
        SyncManager(str(tmp_path), course_id=7, course_name="Micro")
        _close_handles()
        first = tmp_path / ".canvas_sync_corrupted.db"
        first_bytes = first.read_bytes()

        _clobber(db, b"ALSO NOT SQLITE " * 200)
        SyncManager(str(tmp_path), course_id=7, course_name="Micro")
        _close_handles()

        assert first.read_bytes() == first_bytes, "earliest backup was overwritten"
        assert (tmp_path / ".canvas_sync_corrupted_2.db").exists()

    def test_corruption_classifier_separates_the_two_families(self):
        from core.sync_manager import _is_db_corruption
        for damaged in ("file is not a database",
                        "database disk image is malformed",
                        "Integrity check failed: page 3",
                        "file is encrypted or is not a database"):
            assert _is_db_corruption(sqlite3.DatabaseError(damaged)), damaged
        for transient in ("unable to open database file",
                          "database is locked",
                          "attempt to write a readonly database",
                          "disk I/O error",
                          "no such table: sync_manifest"):
            assert not _is_db_corruption(sqlite3.OperationalError(transient)), transient

    def test_healthy_round_trip_is_unchanged(self, tmp_path):
        from core.sync_manager import SyncManager
        _seed_manifest(tmp_path)
        sm = SyncManager(str(tmp_path), course_id=4242, course_name="Macro")
        assert len(sm.load_manifest()["files"]) == 1
        assert sm.db_was_reset is False and sm._db_init_failed is False


# ═══════════════════════════════════════════════════════════════════════
#  JSON stores - unreadable is not empty
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    import core.library as library
    importlib.reload(library)
    library._memo = None
    return library


class TestLibraryCorruption:
    """``_update`` is load -> mutate -> save, so a load that degraded to an
    empty default PERSISTED that emptiness on the very next rename or toggle."""

    def test_invalid_utf8_does_not_raise(self, lib, tmp_path):
        """UnicodeDecodeError is a SIBLING of JSONDecodeError (both derive from
        ValueError), so ``except (json.JSONDecodeError, OSError)`` never caught
        it and the sync page crashed outright. One editor re-saving the file in
        a Danish ANSI codepage is enough to produce it."""
        assert not issubclass(UnicodeDecodeError, json.JSONDecodeError)
        lib.save_pair(101, "C:/Courses/Macro", "Macro", name="Makroøkonomi")
        p = tmp_path / "sync_library.json"
        p.write_bytes(p.read_bytes().replace(
            "Makroøkonomi".encode("utf-8"), "Makroøkonomi".encode("cp1252")))
        lib._memo = None
        assert lib.pairs() == []          # degraded, did not raise
        assert lib.name_index() == {}

    @pytest.mark.parametrize("payload,mode", [
        (b'{"pairs": [ {"id": ', "wb"),                       # truncated JSON
        ("[1, 2, 3]", "w"),                                   # wrong root type
    ])
    def test_damaged_content_is_moved_aside_not_overwritten(
            self, lib, tmp_path, payload, mode):
        lib.save_pair(101, "C:/Courses/Macro", "Macro", name="Makro")
        lib.save_group("Semester 1", [p["id"] for p in lib.pairs()])
        p = tmp_path / "sync_library.json"
        p.write_bytes(payload) if mode == "wb" else p.write_text(payload, encoding="utf-8")
        lib._memo = None

        lib.save_pair(555, "C:/Courses/New", "New")   # triggers load->mutate->save
        quarantined = list(tmp_path.glob("sync_library.corrupt*.json"))
        assert quarantined, "the unreadable file was overwritten, not preserved"
        assert quarantined[0].stat().st_size > 0

    def test_an_unreadable_file_blocks_the_write_entirely(self, lib, tmp_path, monkeypatch):
        """An OSError means the file is momentarily unreachable, NOT damaged -
        so there is nothing to quarantine and nothing may be written over it."""
        lib.save_pair(101, "C:/Courses/Macro", "Macro", name="Makro")
        p = tmp_path / "sync_library.json"
        before = p.read_bytes()

        real_open = open

        def flaky(path, *a, **k):
            if str(path) == str(p) and "r" in (a[0] if a else k.get("mode", "r")):
                raise OSError(5, "device not ready")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", flaky)
        lib._memo = None
        lib.save_pair(999, "C:/Courses/Other", "Other")
        monkeypatch.undo()

        assert p.read_bytes() == before, "wrote over a file it could not read"
        assert not list(tmp_path.glob("sync_library.corrupt*")), \
            "a transient read error must not quarantine a healthy file"

    def test_save_reports_failure_instead_of_swallowing_it(self, lib, monkeypatch):
        monkeypatch.setattr(lib, "_path", lambda *a, **k: __import__("pathlib").Path(
            "Z:/definitely/not/a/real/dir/sync_library.json"))
        assert lib._save({"version": 2, "pairs": [], "groups": []}) is False

    def test_happy_path_is_unchanged(self, lib):
        pid = lib.save_pair(1, "C:/a", "Canvas A", name="Macro")
        lib.set_daily(pid, True)
        lib.save_group("Sem 1", [pid])
        lib._memo = None
        assert len(lib.pairs()) == 1 and len(lib.groups()) == 1
        assert len(lib.daily_pairs()) == 1
        assert lib.name_index() == {lib.link_key(1, "C:/a"): "Macro"}


class TestSyncPairsCorruption:
    """Same shape, different file: ``atomic_update_sync_pairs`` read the list,
    swallowed a decode failure into ``[]``, then WROTE - replacing every saved
    pair with whatever this one call happened to add."""

    def test_damaged_content_is_quarantined(self, tmp_path):
        from shared.helpers import atomic_update_sync_pairs, SYNC_PAIRS_FILENAME
        p = tmp_path / SYNC_PAIRS_FILENAME
        p.write_bytes(b'[{"course_id": 1, "course_name": "\xe6\xf8\xe5"}]')  # cp1252
        atomic_update_sync_pairs(
            lambda ps: ps + [{"course_id": 3, "local_folder": "C:/C",
                              "course_name": "C"}], config_dir=str(tmp_path))
        assert list(tmp_path.glob("canvas_sync_pairs.corrupt*.json")), \
            "unreadable pairs file was destroyed rather than preserved"

    def test_unreadable_file_aborts_the_write(self, tmp_path, monkeypatch):
        from shared.helpers import atomic_update_sync_pairs, SYNC_PAIRS_FILENAME
        p = tmp_path / SYNC_PAIRS_FILENAME
        original = [{"course_id": 1, "local_folder": "C:/A", "course_name": "A"},
                    {"course_id": 2, "local_folder": "C:/B", "course_name": "B"}]
        p.write_text(json.dumps(original), encoding="utf-8")
        before = p.read_bytes()

        real_open = open

        def flaky(path, *a, **k):
            if str(path) == str(p):
                raise OSError(5, "device not ready")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", flaky)
        atomic_update_sync_pairs(lambda ps: [], config_dir=str(tmp_path))
        monkeypatch.undo()
        assert p.read_bytes() == before, "wiped a file it could not read"

    def test_load_sync_pairs_degrades_instead_of_raising(self, tmp_path):
        from shared.helpers import load_sync_pairs, SYNC_PAIRS_FILENAME
        (tmp_path / SYNC_PAIRS_FILENAME).write_bytes(b'[{"course_name": "\xe6\xf8\xe5"}]')
        assert load_sync_pairs(config_dir=str(tmp_path)) == []


# ═══════════════════════════════════════════════════════════════════════
#  Bounded waits - nothing may park the app on a number a server chose
# ═══════════════════════════════════════════════════════════════════════

class TestRetryAfterIsClamped:
    def test_a_huge_header_is_capped(self):
        from core.canvas_logic import parse_retry_after, MAX_RETRY_AFTER_SECONDS
        # 86400 was obeyed literally: a full day on a 1s cancel-polling loop,
        # indistinguishable from a hang.
        assert parse_retry_after("86400", 1) == MAX_RETRY_AFTER_SECONDS

    @pytest.mark.parametrize("raw", ["", "abc", None, "-9", "0",
                                     "Wed, 21 Oct 2015 07:28:00 GMT"])
    def test_unusable_values_fall_back_to_the_callers_backoff(self, raw):
        from core.canvas_logic import parse_retry_after
        assert parse_retry_after(raw, 7) == 7

    def test_a_sane_value_is_honoured_and_is_an_int(self):
        from core.canvas_logic import parse_retry_after
        got = parse_retry_after("5", 1)
        assert got == 5 and isinstance(got, int)

    def test_the_rate_limit_message_round_trips(self):
        """The producer formats the wait into a string that the consumer parses
        back. A float there made the consumer's int() raise, inside the very
        handler meant to absorb the error."""
        from core.canvas_logic import parse_retry_after
        wait = parse_retry_after("5", 1)
        assert float(f"RATE_LIMIT:{wait}".split(":", 1)[1]) == 5.0

    def test_both_engines_use_the_shared_parser(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        for mod in ("core/canvas_logic.py", "sync/execution.py"):
            src = (root / mod).read_text(encoding="utf-8")
            assert "parse_retry_after(" in src, f"{mod} bypasses the clamp"
            assert "int(_retry_after_raw)" not in src, \
                f"{mod} still parses Retry-After by hand"


class _FakeFfmpeg:
    """A process that never exits and never writes - i.e. wedged.

    ``terminate``/``kill`` are what the watchdog is expected to call; recording
    them is how we tell "it gave up" from "it happened to return".
    """

    def __init__(self, grows: bool = False, part_path: str | None = None):
        self.stderr = io.BytesIO(b"")
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._grows = grows
        self._part = part_path
        self._n = 0

    def poll(self):
        if self._grows and self._part:
            # A slow-but-healthy download: keep adding bytes.
            self._n += 1
            with open(self._part, "ab") as fh:
                fh.write(b"x")
            if self._n > 12:                 # finish, so the test terminates
                self.returncode = 0
                return 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.returncode = self.returncode if self.returncode is not None else -15
        return self.returncode


class TestPanoptoStallWatchdog:
    """ffmpeg gets no timeout flags (a version that rejects them would break
    every download), so the STALL guard is the only bound - and the daily
    auto-sync runs unattended, with nobody there to click Cancel."""

    def test_a_wedged_ffmpeg_is_given_up_on(self, tmp_path, monkeypatch):
        import panopto.stream as stream
        monkeypatch.setattr(stream, "_STALL_TIMEOUT_SECONDS", 1)
        fake = _FakeFfmpeg()
        monkeypatch.setattr(stream.subprocess, "Popen", lambda *a, **k: fake)
        out = tmp_path / "Lecture.mp4"

        # Run on a thread with a join timeout. Calling it directly would HANG
        # for ever when the watchdog is absent - which is the very defect under
        # test, so the test would never report it. A test for "this terminates"
        # has to be able to fail rather than hang.
        box = {}

        def run():
            box["r"] = stream._run_ffmpeg_download(
                ["ffmpeg", "-i", "u", str(out)], str(out))

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=45)
        assert not t.is_alive(), \
            "the download never returned - the stall watchdog is not bounding it"

        ok, err = box["r"]
        assert ok is False
        assert "stall" in (err or "").lower(), err
        assert fake.terminated or fake.killed, "the wedged process was left running"
        assert not out.exists(), "a stalled run must not leave a partial recording"

    def test_a_slow_but_progressing_download_is_not_killed(self, tmp_path, monkeypatch):
        """Progress is measured as file GROWTH, not elapsed time - otherwise a
        genuinely slow lecture on a poor connection would be killed mid-way."""
        import panopto.stream as stream
        monkeypatch.setattr(stream, "_STALL_TIMEOUT_SECONDS", 1)
        out = tmp_path / "Lecture.mp4"
        part = str(out.with_suffix("")) + ".part.mp4"
        open(part, "wb").close()
        fake = _FakeFfmpeg(grows=True, part_path=part)
        monkeypatch.setattr(stream.subprocess, "Popen", lambda *a, **k: fake)

        ok, err = stream._run_ffmpeg_download(["ffmpeg", "-i", "u", str(out)], str(out))
        assert not fake.terminated and not fake.killed, \
            "a download that is still producing bytes was killed as stalled"
        assert ok is True, err

    def test_cancellation_still_wins(self, tmp_path, monkeypatch):
        import panopto.stream as stream
        monkeypatch.setattr(stream, "_STALL_TIMEOUT_SECONDS", 999)
        fake = _FakeFfmpeg()
        monkeypatch.setattr(stream.subprocess, "Popen", lambda *a, **k: fake)
        out = tmp_path / "L.mp4"
        ok, err = stream._run_ffmpeg_download(
            ["ffmpeg", "-i", "u", str(out)], str(out), is_cancelled=lambda: True)
        assert ok is False and err == "cancelled"
        assert fake.terminated or fake.killed

    def test_the_killer_reaps_the_child(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "panopto" / "stream.py"
               ).read_text(encoding="utf-8")
        i = src.index("def _stop_ffmpeg")
        body = src[i:i + 700]
        assert body.count("proc.wait(") >= 2, \
            "kill() without a following wait() leaves the child unreaped and " \
            "may keep a handle on the .part file"


# ═══════════════════════════════════════════════════════════════════════
#  Converters - the source may only be deleted once the PDF is proven
# ═══════════════════════════════════════════════════════════════════════

class TestConversionOutputIsVerified:
    """Every Office converter ends by deleting the file it converted FROM. That
    is the one irreversible step in the pipeline and the source is the user's
    own document - possibly its only copy. Word and Excel were doing it on the
    strength of "the COM call did not raise"; Office does not always raise."""

    def test_missing_output_is_rejected(self, tmp_path):
        from converters.verify import pdf_looks_real
        ok, why = pdf_looks_real(tmp_path / "nope.pdf")
        assert not ok and "no PDF" in why

    def test_empty_output_is_rejected(self, tmp_path):
        from converters.verify import pdf_looks_real
        f = tmp_path / "e.pdf"; f.write_bytes(b"")
        ok, why = pdf_looks_real(f)
        assert not ok and "empty" in why

    def test_non_pdf_output_is_rejected(self, tmp_path):
        from converters.verify import pdf_looks_real
        f = tmp_path / "x.pdf"; f.write_bytes(b"<html>error page</html>" * 50)
        ok, why = pdf_looks_real(f)
        assert not ok and "not a PDF" in why

    def test_truncated_output_is_rejected(self, tmp_path):
        from converters.verify import pdf_looks_real
        f = tmp_path / "t.pdf"; f.write_bytes(b"%PDF-1.4\n")
        ok, why = pdf_looks_real(f)
        assert not ok and "truncated" in why

    def test_a_real_pdf_passes(self, tmp_path):
        from converters.verify import pdf_looks_real
        f = tmp_path / "g.pdf"
        f.write_bytes(b"%PDF-1.4\n" + b"0" * 1024 + b"\n%%EOF\n")
        assert pdf_looks_real(f) == (True, "")

    @pytest.mark.parametrize("module,deleted_var", [
        ("converters/word.py", "abs_doc_path"),
        ("converters/excel.py", "src"),
        ("converters/pdf.py", "pptx_path"),
    ])
    def test_the_delete_is_guarded_by_the_check(self, module, deleted_var):
        """Ordering, not adjacency: the verification must PRECEDE the delete on
        the Windows COM success path.

        Parametrized on the VARIABLE, not on the whole delete expression. It
        used to name the literal `abs_doc_path.unlink(missing_ok=True)`, which
        stopped matching the moment those deletes became long-path safe
        (`Path(make_long_path(abs_doc_path)).unlink(...)`) - reporting a missing
        guard where the guard was untouched. Pin the ordering, not the spelling.
        """
        import re
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / module).read_text(encoding="utf-8")
        assert "pdf_looks_real" in src, f"{module} does not verify its output"
        check = src.index("pdf_looks_real(")
        # the delete that follows the COM success path, not the macOS one
        m = re.search(rf"\b{re.escape(deleted_var)}\b[^\n]*?\.unlink\(", src[check:])
        assert m, (
            f"{module} has no delete of `{deleted_var}` after the pdf_looks_real "
            f"check - either the guard moved or the source is no longer consumed")


# ═══════════════════════════════════════════════════════════════════════
#  Bookkeeping that leaks
# ═══════════════════════════════════════════════════════════════════════

class _FakeUI:
    """Minimal UIBridge stand-in - only what the phase guard touches."""

    class _Slot:
        def __init__(self): self.emptied = 0
        def empty(self): self.emptied += 1
        def markdown(self, *a, **k): pass

    def __init__(self):
        self.active_file_placeholder = self._Slot()
        self.header_placeholder = self._Slot()
        self.progress_placeholder = self._Slot()
        self.metrics_placeholder = self._Slot()
        self.log_placeholder = self._Slot()
        self.log_lines = []
        self.pp_success_count = 0
        self.pp_failure_count = 0
        self.error_log_path = None
        self.on_detail_update = None
        self._eta_task = ''
        self._eta = None
        self.archives_skipped = []
        self.generated_sidecar_paths = []

    def is_cancelled(self):
        return False


class TestPostProcessingPhaseIsolation:
    """The nine conversion runners are siblings and a failure in one says
    nothing about the next - a wedged COM server has no bearing on
    HTML->Markdown. Only ONE of them had a per-item handler, and
    run_all_conversions called them all bare, so a single unexpected exception
    took out every later phase AND the retry pass that would have recovered the
    files."""

    def test_a_raising_phase_does_not_propagate(self):
        from converters.post_processing import _run_phase
        ui = _FakeUI()

        def boom(items, ui_):
            raise RuntimeError("COM server died")

        assert _run_phase(boom, [1, 2, 3], ui) is False   # reported, not raised

    def test_a_raising_phase_clears_the_active_file_line(self):
        """The runner clears it on its normal exit; on the exception path it
        would otherwise stay stuck on whichever file blew up."""
        from converters.post_processing import _run_phase
        ui = _FakeUI()
        _run_phase(lambda i, u: (_ for _ in ()).throw(ValueError("x")), [], ui)
        assert ui.active_file_placeholder.emptied >= 1

    def test_a_successful_phase_reports_success(self):
        from converters.post_processing import _run_phase
        ui = _FakeUI()
        seen = []
        assert _run_phase(lambda i, u: seen.append(i), [7], ui) is True
        assert seen == [[7]]

    def test_every_phase_call_site_is_guarded(self):
        """One guard at the boundary cannot be forgotten when a tenth converter
        is added - but only while every call site actually goes through it."""
        import ast
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "converters"
               / "post_processing.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "run_all_conversions")
        bare = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                try:
                    name = ast.unparse(node.func)
                except Exception:
                    continue
                if name.startswith(("run_archive", "run_pptx", "run_html", "run_code",
                                    "run_url", "run_word", "run_excel", "run_video")):
                    bare.append(f"line {node.lineno}: {name}")
        assert not bare, ("conversion phase called directly instead of via "
                          "_run_phase:\n" + "\n".join(bare))

    def test_manifest_bookkeeping_failure_does_not_undo_the_conversion(self):
        """By the time _update_manifest_path runs, the converted file is on disk
        and the original is gone. load_manifest deliberately RE-RAISES database
        errors, so a briefly-locked manifest (antivirus, or the sync that just
        wrote to it) aborted the phase mid-way."""
        from converters.post_processing import _update_manifest_path
        from pathlib import Path as _P

        class _ExplodingSM:
            local_path = _P("C:/course")
            def load_manifest(self):
                raise RuntimeError("Sync database could not be initialized")

        # Must not raise - the file is already converted.
        _update_manifest_path(_ExplodingSM(), _P("C:/course/a.html"), _P("C:/course/a.md"))


class TestProgressHooksLeaveATrace:
    """A repaint hook must never abort a run - and must never be silent either.

    `sync/analysis.py`'s hook raised NameError on EVERY tick for months: the
    analysis panel simply never painted, users saw a bare Cancel button on an
    empty page, and nothing anywhere recorded why. It was fixed there; the
    Panopto hook in sync_ui.py had the identical shape and was not.

    Enforced as a FAMILY, with a size threshold. A 1-3 line `except Exception:
    pass` around a best-effort formatting call is ordinary defensive code; the
    thing that hides a defect is a silent handler wrapped around a large body.
    """

    #: lines of guarded body above which a silent swallow is a defect
    MAX_SILENT_SPAN = 10

    HOOKISH = ("progress", "hook", "callback", "_render", "repaint",
               "_paint", "on_event", "update_ui", "_tick")

    def _offenders(self):
        import ast
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent
        out = []
        for pkg in ("app.py", "sync_ui.py", "ui", "sync", "engine", "core",
                    "panopto", "converters", "shared"):
            p = root / pkg
            files = [p] if p.is_file() else sorted(p.rglob("*.py"))
            for f in files:
                try:
                    tree = ast.parse(f.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for fn in ast.walk(tree):
                    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not any(k in fn.name.lower() for k in self.HOOKISH):
                        continue
                    for tr in ast.walk(fn):
                        if not isinstance(tr, ast.Try):
                            continue
                        span = (tr.body[-1].end_lineno or 0) - tr.body[0].lineno + 1
                        if span <= self.MAX_SILENT_SPAN:
                            continue
                        for h in tr.handlers:
                            t = ast.unparse(h.type) if h.type else "BARE"
                            broad = (h.type is None or "Exception" in t
                                     or "BaseException" in t)
                            if not broad:
                                continue
                            body = " ".join(ast.unparse(s) for s in h.body)
                            if any(k in body for k in
                                   ("log", "warn", "error", "raise", "print")):
                                continue
                            out.append(f"{f.relative_to(root)}:{h.lineno} "
                                       f"{fn.name}() swallows {span} lines silently")
        return out

    def test_no_large_repaint_hook_swallows_silently(self):
        offenders = self._offenders()
        assert not offenders, (
            "a progress/repaint hook must log what it swallows (see "
            "sync/analysis.py:sync_progress_hook for the pattern):\n"
            + "\n".join(offenders))

    def test_the_panopto_hook_logs_the_first_failure_with_a_traceback(self):
        """First failure carries the stack; the rest are only counted. This one
        fires per download/transcribe EVENT, so an unconditional exc_info would
        bury the run's real errors under hundreds of identical stacks."""
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "sync_ui.py"
               ).read_text(encoding="utf-8")
        i = src.index("Panopto progress repaint failed")
        block = src[i - 800:i + 400]
        assert "exc_info=True" in block, "the first failure carries no traceback"
        assert "_pan_hook_errs" in block, "repeat failures are not throttled"


class TestSettingsFileIsNeverTruncated:
    """``open(path, 'w')`` truncates FIRST and writes second, so a crash or a
    full disk in between leaves the settings file empty or half-written.

    The config was written in FIVE places and only three did tmp + fsync +
    os.replace. The two that did not were the legacy token-migration paths in
    restore_saved_session - which run at STARTUP, on the very run that moves a
    token out of the JSON into the keyring."""

    def test_no_truncating_write_to_the_config_file_remains(self):
        import re
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "ui" / "auth.py"
               ).read_text(encoding="utf-8")
        offenders = []
        for i, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or s.startswith('"') or s.startswith("``"):
                continue
            if re.search(r"open\(\s*CONFIG_FILE\s*,\s*['\"]w", s):
                offenders.append(f"ui/auth.py:{i}: {s[:70]}")
        assert not offenders, (
            "settings written by truncation - use write_config_atomically:\n"
            + "\n".join(offenders))

    def test_every_config_write_goes_through_a_tmp_and_replace(self):
        """Covers the three sites that inline the pattern as well as the helper:
        whichever form is used, the file must never be truncated in place."""
        import re
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "ui" / "auth.py"
               ).read_text(encoding="utf-8")
        # every write of a config dict is either the helper or a tmp write
        writes = [i for i, l in enumerate(src.splitlines(), 1)
                  if re.search(r"json\.dump\(config", l)]
        assert writes, "no config writes found - did the file move?"
        for ln in writes:
            window = "\n".join(src.splitlines()[max(0, ln - 6):ln + 6])
            assert ("os.replace" in window or "_tmp_config" in window
                    or "write_config_atomically" in window), (
                f"ui/auth.py:{ln} writes the config without tmp+replace")

    def test_the_helper_round_trips_and_never_raises(self, tmp_path, monkeypatch):
        import json as _json
        import ui.auth as auth
        monkeypatch.setattr(auth, "CONFIG_FILE", str(tmp_path / "settings.json"))
        cfg = {"api_url": "https://x.instructure.com", "n": 1}
        assert auth.write_config_atomically(cfg) is True
        assert _json.loads((tmp_path / "settings.json").read_text(encoding="utf-8")) == cfg
        assert not (tmp_path / "settings.json.tmp").exists(), "temp file left behind"

        # an unwritable target must be reported, not raised - a settings write
        # may not abort a login
        monkeypatch.setattr(auth, "CONFIG_FILE", str(tmp_path / "no" / "such" / "s.json"))
        assert auth.write_config_atomically(cfg) is False

    def test_an_existing_config_survives_a_failed_write(self, tmp_path, monkeypatch):
        """The whole point: the old file stays intact until the new one is
        complete."""
        import json as _json
        import ui.auth as auth
        target = tmp_path / "settings.json"
        good = {"api_url": "https://x.instructure.com", "keep": "me"}
        target.write_text(_json.dumps(good), encoding="utf-8")
        monkeypatch.setattr(auth, "CONFIG_FILE", str(target))

        real_replace = os.replace

        def boom(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(auth.os, "replace", boom)
        assert auth.write_config_atomically({"wiped": True}) is False
        monkeypatch.setattr(auth.os, "replace", real_replace)

        assert _json.loads(target.read_text(encoding="utf-8")) == good, \
            "a failed write destroyed the existing settings"


class TestSecondaryContentCategoryIsolation:
    """The seven secondary-content categories are independent - a malformed quiz
    says nothing about the user's submissions - but they were seven bare calls
    in a row. The first to raise skipped every category after it AND skipped the
    `asyncio.gather` that awaits the attachment tasks assignments/announcements
    had already scheduled, so `asyncio.run` cancelled them at loop close and
    those files silently never arrived."""

    def _fn(self):
        import ast
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "core" / "canvas_logic.py"
               ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        return next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "_download_secondary_content"), src

    def test_every_category_is_individually_guarded(self):
        import ast
        fn, _ = self._fn()
        bare = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                try:
                    name = ast.unparse(node.func)
                except Exception:
                    continue
                if "_fetch_and_save_" in name and name.startswith("self."):
                    bare.append(f"line {node.lineno}: {name}")
        assert not bare, (
            "secondary-content category called directly instead of via "
            "_sec_category:\n" + "\n".join(bare))

    def test_all_seven_categories_are_registered(self):
        import ast
        fn, _ = self._fn()
        labels = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "_sec_category"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                labels.add(node.args[0].value)
        assert labels == {"assignments", "syllabus", "announcements",
                          "discussions", "quizzes", "submissions", "rubrics"}, labels

    def test_queued_attachments_are_awaited_in_a_finally(self):
        """The gather must survive a category blowing up - those tasks are
        already scheduled, and abandoning them loses real files."""
        import ast
        fn, _ = self._fn()
        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
        assert tries, "the category block is not wrapped in try/finally"
        assert any("asyncio.gather" in ast.unparse(t.finalbody) for t in tries), (
            "the attachment gather is not in a finally - a failing category "
            "would abandon every attachment already queued")

    def test_a_failing_category_reports_which_one(self):
        """One generic 'Canvas Content Error' gave the user no way to tell
        which of the seven parts actually ran."""
        import ast
        fn, _ = self._fn()
        helper = next(n for n in ast.walk(fn)
                      if isinstance(n, ast.FunctionDef) and n.name == "_sec_category")
        body = ast.unparse(helper)
        assert "label" in body and "DownloadError" in body
        assert "exc_info=True" in body, "a failed category leaves no traceback"


class TestNewVersionDiversionCannotBeSkipped:
    """`_NewVersion` is what stops a re-download overwriting a student's edited
    copy. The download engine committed to it AFTER announcing it, so anything
    the progress callback raised skipped the commit and left `filepath` pointing
    at the edited file - which the download below then overwrote, silently,
    because the enclosing handler was a bare `pass`."""

    def _block(self):
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "core" / "canvas_logic.py"
               ).read_text(encoding="utf-8")
        start = src.index("_diverted = self._handle_conflict(")
        return src[start:start + 2400]

    def test_the_redirect_is_committed_before_the_announcement(self):
        b = self._block()
        commit = b.index("filepath = _diverted")
        announce = b.index("progress_callback(")
        assert commit < announce, (
            "the _NewVersion redirect is committed after the progress callback - "
            "anything the callback raises overwrites the user's edited file")

    def test_the_announcement_names_the_file_the_user_edited(self):
        """After the reorder `filename` is already the NEW name, so the message
        must use the captured original or it reports the wrong file."""
        b = self._block()
        assert "_original_name = filename" in b
        assert "_original_name" in b[b.index("progress_callback("):]

    def test_the_existing_file_handler_is_not_silent(self):
        """Asserted on the parsed HANDLER BODY, not on a substring of the file.

        The substring form was fooled by a mutation that turned the logging call
        into a dead `_unused = (...)` assignment: the text `exc_info=True` was
        still present, so the test passed while the handler had gone silent.
        What matters is that a logging CALL actually executes.
        """
        import ast
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "core" / "canvas_logic.py"
               ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        handler = None
        for n in ast.walk(tree):
            if isinstance(n, ast.ExceptHandler) and n.name == "_exists_err":
                handler = n
                break
        assert handler is not None, "the existing-file handler has been renamed away"

        logged = False
        for stmt in handler.body:
            # a bare expression whose value is a call to log_debug/logger.*
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
                continue
            fn = ast.unparse(stmt.value.func)
            if "log" in fn.lower():
                logged = True
        assert logged, (
            "the handler executes no logging call - a failure that may have "
            "skipped _NewVersion protection would be unrecorded")
        assert not any(isinstance(s, ast.Pass) for s in handler.body), \
            "handler still contains a bare pass"


class TestSourceDeletionIsAlwaysEarned:
    """Six converters delete the file they converted FROM. That is the only
    irreversible step in the pipeline and the file is the user's own, so every
    one of them must PROVE the output first. Audited as a family, because the
    pattern was right in three of them (`code`, `md`, `url`) and absent in the
    other three - which is exactly how it stayed unnoticed."""

    def test_generic_verifier_rejects_missing_empty_and_stub(self, tmp_path):
        from converters.verify import file_has_content
        assert not file_has_content(tmp_path / "nope.mp3")[0]
        (tmp_path / "e.mp3").write_bytes(b"")
        assert not file_has_content(tmp_path / "e.mp3")[0]
        (tmp_path / "s.mp3").write_bytes(b"x" * 10)
        assert not file_has_content(tmp_path / "s.mp3", min_bytes=1024)[0]
        (tmp_path / "g.mp3").write_bytes(b"x" * 4096)
        assert file_has_content(tmp_path / "g.mp3", min_bytes=1024) == (True, "")

    def test_video_verifies_the_mp3_before_deleting_the_video(self):
        """The stakes are the highest in the app: a lecture recording, possibly
        multi-GB and - for a Panopto capture - not re-downloadable. The flag was
        set the instant write_audiofile RETURNED, and nothing looked at what it
        had actually produced."""
        import inspect
        from converters import video
        src = inspect.getsource(video.convert_video_to_mp3)
        assert "file_has_content" in src, "the MP3 is still unverified"
        # ordering: the check must precede `conversion_success = True`, which is
        # what the finally-block deletion keys off.
        chk = src.index("file_has_content(")
        flag = src.index("conversion_success = True")
        assert chk < flag, "the video is marked deletable before the MP3 is proven"

    def test_video_verification_precedes_the_return(self):
        """It cannot live in the `finally`: by then the function has already
        RETURNED the mp3 path, so the caller records a success and repoints the
        manifest at a file that is not there."""
        import inspect, ast
        from converters import video
        tree = ast.parse(inspect.getsource(video.convert_video_to_mp3))
        fn = tree.body[0]
        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
        for t in tries:
            body = "\n".join(ast.unparse(n) for n in t.finalbody)
            assert "file_has_content" not in body, \
                "verification in the finally runs after the value is returned"

    def test_archive_keeps_an_archive_that_yielded_nothing(self, tmp_path):
        """Both extraction paths can legitimately produce nothing while raising
        nothing: _filter_zip_members strips every __MACOSX/ and ._* entry, and
        tarfile's `data` filter SILENTLY SKIPS unsafe members."""
        import zipfile
        from converters.archive import extract_archive
        z = tmp_path / "macmeta.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("__MACOSX/._a", "junk")
            zf.writestr("__MACOSX/._b", "junk")
        result = extract_archive(str(z))
        assert z.exists(), "the archive was deleted with nothing extracted"
        assert result is not True
        assert not (tmp_path / "macmeta").exists(), "empty extraction folder left behind"

    def test_archive_still_extracts_and_removes_a_real_one(self, tmp_path):
        import zipfile
        from converters.archive import extract_archive
        z = tmp_path / "lecture.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("notes.txt", "hello")
            zf.writestr("sub/data.csv", "a,b\n1,2")
        assert extract_archive(str(z)) is True
        assert not z.exists(), "a healthy archive should be removed after extraction"
        assert (tmp_path / "lecture" / "notes.txt").read_text() == "hello"

    def test_no_local_import_shadows_an_earlier_use(self):
        """`import x` ANYWHERE in a function makes `x` local for the WHOLE
        function, so a reference above it raises UnboundLocalError - silently,
        because an enclosing handler catches it and reports the wrong reason.
        Introduced by this very audit in archive.py and caught by a real run;
        the same shape is what cost a debugging cycle on `isolate` in
        core/canvas_logic.py."""
        import ast
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent
        offenders = []
        for pkg in ("core", "converters", "shared", "panopto", "sync", "engine", "ui"):
            for f in (root / pkg).rglob("*.py"):
                try:
                    tree = ast.parse(f.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for fn in ast.walk(tree):
                    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    imports = {}
                    for n in ast.walk(fn):
                        if isinstance(n, ast.Import):
                            for a in n.names:
                                nm = a.asname or a.name.split('.')[0]
                                imports[nm] = min(imports.get(nm, n.lineno), n.lineno)
                        elif isinstance(n, ast.ImportFrom):
                            for a in n.names:
                                nm = a.asname or a.name
                                imports[nm] = min(imports.get(nm, n.lineno), n.lineno)
                    if not imports:
                        continue
                    # annotations evaluate at def-time in the ENCLOSING scope
                    skip = set()
                    if fn.returns is not None:
                        skip |= {id(x) for x in ast.walk(fn.returns)}
                    for a in (list(fn.args.args) + list(fn.args.kwonlyargs)
                              + list(fn.args.posonlyargs)):
                        if a.annotation is not None:
                            skip |= {id(x) for x in ast.walk(a.annotation)}
                    for stmt in fn.body:
                        for n in ast.walk(stmt):
                            if id(n) in skip:
                                continue
                            if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                                    and n.id in imports and n.lineno < imports[n.id]):
                                offenders.append(
                                    f"{f.relative_to(root)}:{n.lineno} {fn.name}() "
                                    f"uses '{n.id}' before its local import "
                                    f"(line {imports[n.id]})")
        assert not offenders, "UnboundLocalError waiting to happen:\n" + "\n".join(offenders)


class TestOfficeShadowUsesLongPaths:
    """office_safe_path exists SOLELY for paths >= 240 chars, and then read the
    source and wrote the destination without the prefix - so on a default
    Windows install (LongPathsEnabled = 0) the one function meant to handle long
    paths could not."""

    def test_the_shadow_copy_and_move_back_are_prefixed(self):
        import inspect
        from shared import helpers
        src = inspect.getsource(helpers.office_safe_path)
        assert "shutil.copy2(make_long_path(resolved)" in src, \
            "the shadow copy still reads the long source unprefixed"
        assert "shutil.move(str(temp_pdf), make_long_path(original_pdf))" in src, \
            "the move-back still writes the long destination unprefixed"
        assert "Path(make_long_path(original_pdf.parent)).mkdir" in src, \
            "the destination mkdir is still unprefixed"

    def test_what_is_YIELDED_stays_unprefixed(self):
        """The asymmetry is the whole point: our own file operations need the
        prefix, but Office COM chokes on a prefixed path - which is why the
        shadowing exists at all."""
        import inspect
        from shared import helpers
        src = inspect.getsource(helpers.office_safe_path)
        for line in src.splitlines():
            if line.strip().startswith("yield"):
                assert "make_long_path" not in line, \
                    f"a prefixed path is being handed to Office COM: {line.strip()}"


class TestDownloadLockAccounting:
    def test_release_pops_on_non_positive_count(self):
        """A run on a NEW event loop replaces a stale entry; the previous loop's
        holders then release against the replacement and drive its count
        negative, so an exact ``== 0`` test never fires and the entry is pinned
        for the life of the process."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "core" / "canvas_logic.py"
               ).read_text(encoding="utf-8")
        i = src.index("def _release_slot")
        assert 'entry["count"] <= 0' in src[i:i + 900], \
            "release still uses an exact-zero test and can leak entries"


class TestCourseCacheInflightClaim:
    def test_a_failed_thread_start_releases_the_claim(self, monkeypatch):
        """The claim in _inflight is made on the promise that _refresh will run
        and pop it. If the thread never starts, later calls wait the full 90s on
        an Event nothing will ever set."""
        import core.course_cache as cc
        importlib.reload(cc)
        key = ("tok", "https://x.instructure.com")
        cc._cache[key] = {"courses": ["a"], "at": 0.0}      # ancient -> refresh due

        def no_thread(*a, **k):
            raise RuntimeError("can't start new thread")
        monkeypatch.setattr(cc.threading.Thread, "start", no_thread)
        try:
            cc.fetch_courses(*key)
        except RuntimeError:
            pytest.fail("a failed refresh-thread start must not propagate")
        finally:
            monkeypatch.undo()
        assert key not in cc._inflight, "stale in-flight claim would stall later calls"
        cc.clear()
