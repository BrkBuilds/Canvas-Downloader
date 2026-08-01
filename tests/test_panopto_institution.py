"""Tests for institution-level Panopto detection.

The fixture is the REAL external-tool list from a live Canvas (CBS, probed
2026-07-31), including the seven tools whose ``domain`` is null - that shape
crashed the first version of the probe script and is the single most likely way
this matcher breaks in the field.

The other 22 tools are as valuable as the Panopto one: they are the false
positives a sloppy matcher would produce, taken from a real institution rather
than invented.
"""

from __future__ import annotations

import pathlib

import pytest

from panopto.institution import ToolScan, looks_panopto, scan_external_tools

REPO = pathlib.Path(__file__).resolve().parent.parent

# Real payload, trimmed to the fields the matcher reads. Null domains preserved.
CBS_TOOLS = [
    {"id": 850, "name": " FeedbackFruits Europe", "domain": "api.feedbackfruits.com"},
    {"id": 795, "name": "Admin and Course Analytics", "domain": "canvas-analytics-iad-prod.inscloudgate.net"},
    {"id": 836, "name": "Attendance", "domain": None},
    {"id": 2, "name": "Canvas Commons", "domain": "https://lor.instructure.com"},
    {"id": 1, "name": "Chat", "domain": None},
    {"id": 232, "name": "Course Evaluation", "domain": "explorance.com"},
    {"id": 634, "name": "Course Readings", "domain": None},
    {"id": 657, "name": "Course Readings", "domain": "exlibrisgroup.com"},
    {"id": 877, "name": "Lucid Integration", "domain": "integration.lucid.app"},
    {"id": 904, "name": "Microsoft Teams Meetings", "domain": "msteams-lti-iad-prod.inscloudgate.net"},
    {"id": 126, "name": "Office 365", "domain": "office365-dub-prod.instructure.com"},
    {"id": 254, "name": "OneNote Class Notebook", "domain": None},
    {"id": 863, "name": "Panopto videos", "domain": "cbs.cloud.panopto.eu",
     "url": "https://cbs.cloud.panopto.eu/Panopto/LTI/LTI.aspx"},
    {"id": 138, "name": "Pearson", "domain": None},
    {"id": 139, "name": "Pearson MyLab and Mastering", "domain": None},
    {"id": 218, "name": "Piazza", "domain": None},
    {"id": 899, "name": "Portfolio LTI Client", "domain": "iad.portfolio.instructure.com"},
    {"id": 137, "name": "Quizzes 2", "domain": None},
    {"id": 854, "name": "SCORM", "domain": "scone-prod.eu-west-1.insops.net"},
    {"id": 15, "name": "TED Ed", "domain": "www.edu-apps.org"},
    {"id": 14, "name": "Twitter", "domain": "edu-apps.org"},
    {"id": 13, "name": "Vimeo", "domain": "edu-apps.org"},
    {"id": 3, "name": "YouTube", "domain": "www.edu-apps.org"},
]


class FakeREST:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_all(self, path, params=None):
        self.calls.append((path, params))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


# ── The matcher ──────────────────────────────────────────────────────────────

def test_matches_the_real_panopto_tool():
    tool = next(t for t in CBS_TOOLS if t["id"] == 863)
    assert looks_panopto(tool) is True


def test_no_false_positives_across_a_real_institution():
    """Every other tool at a real university must NOT match."""
    others = [t for t in CBS_TOOLS if t["id"] != 863]
    assert [t["name"] for t in others if looks_panopto(t)] == []


@pytest.mark.parametrize("tool", [
    {"id": 1, "name": "Attendance", "domain": None},
    {"id": 2, "name": None, "domain": None, "url": None},
    {"id": 3},
    {},
])
def test_null_fields_never_raise(tool):
    """7 of 23 real tools have a null domain. An unguarded .lower() raises -
    it did, on the first version of the probe script."""
    assert looks_panopto(tool) is False


@pytest.mark.parametrize("bad", [None, "panopto", 863, [], object()])
def test_non_dict_input_is_false_not_an_exception(bad):
    assert looks_panopto(bad) is False


def test_vanity_hosted_panopto_is_matched_by_url_path():
    """An institution fronting Panopto with its own CNAME has no "panopto" in
    the hostname - but the LTI launch PATH is Panopto's own product route.
    Same trap `stream.py:_cookie_header` documents for cookies."""
    vanity = {
        "id": 5001, "name": "Lecture Recordings",
        "domain": "video.university.edu",
        "url": "https://video.university.edu/Panopto/LTI/LTI.aspx",
    }
    assert "panopto" not in (vanity["domain"] or "").lower()
    assert "panopto" not in (vanity["name"] or "").lower()
    assert looks_panopto(vanity) is True


def test_matched_by_name_alone():
    assert looks_panopto({"id": 7, "name": "Panopto Video", "domain": None}) is True


# ── The scan ─────────────────────────────────────────────────────────────────

def test_scan_resolves_ids_dynamically():
    scan = scan_external_tools(FakeREST(CBS_TOOLS), 45899)
    assert scan.resolved is True
    assert scan.has_panopto is True
    assert scan.panopto_tool_ids == frozenset({863})
    assert len(scan.known_tool_ids) == len(CBS_TOOLS)


def test_scan_uses_include_parents():
    """Without it the endpoint returns zero tools in every course (measured),
    so the whole detection silently degrades to "no Panopto"."""
    rest = FakeREST(CBS_TOOLS)
    scan_external_tools(rest, 45899)
    path, params = rest.calls[0]
    assert "external_tools" in path
    assert params.get("include_parents") == "true"


def test_institution_without_panopto():
    tools = [t for t in CBS_TOOLS if t["id"] != 863]
    scan = scan_external_tools(FakeREST(tools), 45899)
    assert scan.resolved is True
    assert scan.has_panopto is False
    assert scan.should_skip_panopto() is True


@pytest.mark.parametrize("payload", [[], None, {}, "nope", RuntimeError("boom")])
def test_failures_never_conclude_absence(payload):
    """Fail OPEN. An empty list is what a course returns WITHOUT include_parents
    and what a 401 degrades to - concluding "no Panopto" from it would silently
    remove a configured feature with no error anywhere."""
    scan = scan_external_tools(FakeREST(payload), 45899)
    assert scan.should_skip_panopto() is False


def test_missing_course_id_is_unresolved():
    assert scan_external_tools(FakeREST(CBS_TOOLS), None).should_skip_panopto() is False


# ── The handshake filter ─────────────────────────────────────────────────────

def test_known_non_panopto_tool_is_skippable():
    """634 = the ExLibris library tool. All 12 of its module items in course
    45899 got a full LTI handshake that could only ever return nothing."""
    scan = scan_external_tools(FakeREST(CBS_TOOLS), 45899)
    assert scan.is_known_non_panopto_tool(634) is True


def test_panopto_tool_is_never_skippable():
    scan = scan_external_tools(FakeREST(CBS_TOOLS), 45899)
    assert scan.is_known_non_panopto_tool(863) is False


@pytest.mark.parametrize("tool_id", [None, 999999, "", "abc"])
def test_unknown_tool_is_never_skipped(tool_id):
    """Skip only what we can PROVE is not Panopto. An id we never saw keeps its
    handshake, so a course-level Panopto install can never be lost."""
    scan = scan_external_tools(FakeREST(CBS_TOOLS), 45899)
    assert scan.is_known_non_panopto_tool(tool_id) is False


def test_unresolved_scan_skips_nothing():
    assert ToolScan().is_known_non_panopto_tool(634) is False


def test_string_tool_ids_are_coerced():
    """Canvas has returned ids as strings on some endpoints."""
    scan = scan_external_tools(FakeREST(CBS_TOOLS), 45899)
    assert scan.is_known_non_panopto_tool("634") is True


# ── The rule the whole feature rests on ──────────────────────────────────────

def test_global_toggle_defaults_on(tmp_path, monkeypatch):
    """Off-by-default would silently strip a headline feature from every
    existing install and neuter the three presets that include recordings."""
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    from panopto import settings as ps
    assert ps.is_globally_enabled() is True


def test_global_toggle_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    from panopto import settings as ps
    assert ps.set_globally_enabled(False) is True
    assert ps.is_globally_enabled() is False
    assert ps.set_globally_enabled(True) is True
    assert ps.is_globally_enabled() is True


def test_global_toggle_preserves_other_settings(tmp_path, monkeypatch):
    """The file is shared with ui/auth.py and the "panopto" contract block."""
    import json
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    cfg = tmp_path / "canvas_downloader_settings.json"
    cfg.write_text(json.dumps({
        "show_help_text": False,
        "panopto_notice_ack_version": 1,
        "panopto": {"model": "large-v3", "device": "cuda"},
    }), encoding="utf-8")

    from panopto import settings as ps
    assert ps.set_globally_enabled(False) is True

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["show_help_text"] is False
    assert data["panopto_notice_ack_version"] == 1
    assert data["panopto"] == {"model": "large-v3", "device": "cuda"}
    assert data[ps.GLOBAL_ENABLED_KEY] is False


def test_global_toggle_is_not_a_contract_key():
    """In PANOPTO_DEFAULTS it would be copied into every composed run config
    and persisted into every synced folder's manifest."""
    from panopto.settings import GLOBAL_ENABLED_KEY, PANOPTO_DEFAULTS, extract_contract
    assert GLOBAL_ENABLED_KEY not in PANOPTO_DEFAULTS
    assert GLOBAL_ENABLED_KEY not in extract_contract(dict(PANOPTO_DEFAULTS))


# ── The handshake filter, end to end through discover_course_videos ──────────

@pytest.fixture(autouse=True)
def _clear_scan_memo():
    """The per-host memo is module-level and would leak between tests."""
    from panopto import institution
    institution._SCAN_MEMO.clear()
    yield
    institution._SCAN_MEMO.clear()


def _run_discovery(monkeypatch, module_items, tools):
    """Drive discover_course_videos, returning (videos, handshaked_item_ids).

    Counts DISTINCT module items, not raw lti_launch calls: discovery tries the
    module-item launch and then a legacy fallback, so one item can produce two
    calls. The number of items that reach pass 2 is what the filter controls.
    """
    import re

    import panopto.discovery as pdisc

    modules = [{"id": 1, "name": "Tema 1", "items": module_items}]
    handshakes = []

    class _FakeREST:
        base = "https://canvas.test"

        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            if path.endswith("/external_tools"):
                return tools
            return modules if path.endswith("/modules") else []

        def get_one(self, path):
            return {"url": "https://canvas.test/api/sessionless_launch?x=1"}

    def _fake_lti(url, token):
        handshakes.append(url)
        return (None, "", None, None, None)

    monkeypatch.setattr(pdisc, "_CanvasREST", _FakeREST)
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)
    videos = pdisc.discover_course_videos("https://canvas.test", "tok", 1)
    item_ids = {m.group(1) for u in handshakes
                for m in [re.search(r"module_item_id=(\d+)", u)] if m}
    return videos, item_ids


def test_known_non_panopto_items_never_get_a_handshake(monkeypatch):
    """Measured on a real account: 12 ExLibris items in one course, each costing
    ~1-2s of LTI handshake that could only ever return nothing."""
    items = [{"id": i, "title": f"Reading {i}", "type": "ExternalTool",
              "content_id": 634} for i in range(1, 13)]
    _, handshakes = _run_discovery(monkeypatch, items, CBS_TOOLS)
    assert handshakes == set()


def test_panopto_items_still_get_their_handshake(monkeypatch):
    """The 36/36 course. Panopto module items carry the GENERIC LTI.aspx url
    with no session id, so the handshake is the only way to resolve them -
    skipping one loses a recording outright."""
    items = [{"id": i, "title": f"Lecture {i}", "type": "ExternalTool",
              "content_id": 863} for i in range(1, 6)]
    _, handshakes = _run_discovery(monkeypatch, items, CBS_TOOLS)
    assert len(handshakes) == 5


def test_unknown_tool_still_gets_a_handshake(monkeypatch):
    """Skip only what we can PROVE is not Panopto - a course-level Panopto
    install would carry an id absent from the account list."""
    items = [{"id": 1, "title": "Mystery tool", "type": "ExternalTool",
              "content_id": 999999}]
    _, handshakes = _run_discovery(monkeypatch, items, CBS_TOOLS)
    assert len(handshakes) == 1


def test_item_with_an_embedded_panopto_id_is_never_skipped(monkeypatch):
    """Even when the tool is provably another vendor's, an embedded recording
    id is a real recording and must survive."""
    guid = "0d78cddd-c122-444c-a358-b389015d0350"
    items = [{"id": 1, "title": "Embedded", "type": "ExternalTool",
              "content_id": 634,
              "external_url": f"https://x.test/Viewer.aspx?id={guid}"}]
    videos, _ = _run_discovery(monkeypatch, items, CBS_TOOLS)
    assert guid in {v.video_id for v in videos}


def test_an_unresolved_scan_skips_nothing(monkeypatch):
    """Fail open. If the tool lookup fails, every item keeps its handshake -
    the old behaviour exactly."""
    items = [{"id": i, "title": f"Reading {i}", "type": "ExternalTool",
              "content_id": 634} for i in range(1, 4)]
    _, handshakes = _run_discovery(monkeypatch, items, [])
    assert len(handshakes) == 3


def test_scan_is_memoised_per_host(monkeypatch):
    """One ~230ms lookup per Canvas, not one per course - 33 courses would
    otherwise pay ~7.6s of latency to learn a single institution-wide fact."""
    from panopto import institution

    calls = []

    class _R:
        base = "https://canvas.test"

        def get_all(self, path, params=None):
            calls.append(path)
            return CBS_TOOLS

    r = _R()
    for _ in range(5):
        institution.cached_scan(r, 1)
    assert len(calls) == 1


def test_a_failed_scan_is_not_memoised():
    """Otherwise one network blip disables the optimisation for the whole
    process - and, worse, freezes an "unknown" answer nothing retries."""
    from panopto import institution

    calls = []

    class _R:
        base = "https://canvas.test"

        def get_all(self, path, params=None):
            calls.append(path)
            return []

    r = _R()
    institution.cached_scan(r, 1)
    institution.cached_scan(r, 1)
    assert len(calls) == 2
    # Assert the INVARIANT, not just the call count. There are two guards here
    # (write-side "only cache resolved", read-side "only trust resolved"), so a
    # call-count check alone passes with either one deleted - found by mutating
    # the write guard away and watching this test stay green.
    assert institution._SCAN_MEMO == {}, "an unresolved scan was cached"


# ── Robustness review fixes (2026-07-31) ─────────────────────────────────────

def test_no_host_means_no_caching():
    """Caching under an empty key would make one institution's answer apply to
    the next - which for this fact silently disables Panopto at a university
    that has it, or enables a pointless search at one that does not."""
    from panopto import institution

    calls = []

    class _NoBase:
        def get_all(self, path, params=None):
            calls.append(path)
            return CBS_TOOLS

    r = _NoBase()
    institution.cached_scan(r, 1)
    institution.cached_scan(r, 1)
    assert len(calls) == 2
    assert institution._SCAN_MEMO == {}


def test_only_one_cache_for_the_institution_answer():
    """shared.legal.institution_scan must DELEGATE, not keep a second copy.

    It used to cache in session state while panopto.institution cached in a
    module dict: two lookups for one fact, and a window where the UI and the
    discovery engine could disagree about whether Panopto exists at all.
    """
    src = (REPO / "shared" / "legal.py").read_text(encoding="utf-8")
    fn = src[src.index("def institution_scan"):]
    fn = fn[:fn.index("\ndef ", 1)]
    assert "cached_scan(" in fn
    assert "scan_external_tools(" not in fn, (
        "institution_scan bypasses the shared memo - two caches again"
    )


def test_course_id_also_comes_from_pairs():
    """Sync and Today never populate the course-LIST keys; they work from pairs.
    Without a pair fallback the scan stays unresolved there, and the Today
    opt-in card shows at universities with no Panopto at all."""
    src = (REPO / "shared" / "legal.py").read_text(encoding="utf-8")
    fn = src[src.index("def _any_course_id"):]
    fn = fn[:fn.index("\ndef ", 1)]
    assert "sync_pairs" in fn
    assert "resolve_today_pairs" in fn


def test_shared_logger_reaches_the_debug_file():
    """shared.legal logs every Panopto consent decision at INFO. The debug
    bridge keeps INFO only for names in _APP_LOGGER_PREFIXES and WARNING+ for
    everything else - 'shared' was missing, so those records were dropped."""
    from core.canvas_debug import _APP_LOGGER_PREFIXES
    assert "shared" in _APP_LOGGER_PREFIXES


def test_consent_decisions_are_logged():
    """The unavailable path is invisible on screen - no dialog, no message. If
    it is not in the log, "why didn't it download my lectures?" is unanswerable."""
    src = (REPO / "shared" / "legal.py").read_text(encoding="utf-8")
    assert "notice ACCEPTED" in src
    assert "notice DECLINED" in src
    assert "Panopto skipped:" in src


def test_the_handshake_filter_logs_what_it_skipped():
    src = (REPO / "panopto" / "discovery.py").read_text(encoding="utf-8")
    assert "non-Panopto ExternalTool item" in src


def test_completion_tracker_inset_is_restored():
    """Measured 2026-07-31: the tracker sat at 0px on the completion screens and
    32px everywhere else, because its inset is accidental (one 16px flex gap per
    in-flow style host above it) and the completion screens inject none."""
    css = (REPO / "styles" / "global.css").read_text(encoding="utf-8")
    # The whole SELECTOR, not two substrings that both happen to occur in a
    # 2,000-line file: `st-key-cd_wizard_` appears in a dozen other rules, so a
    # token check stayed green when the selector was renamed (found by mutation
    # - the third time this exact mistake showed up in this session's tests).
    rule = 'div[class*="st-key-cd_wizard_"]:has([class*="_complete_st_active"])'
    assert rule in css, "the completion-screen tracker inset rule is gone"
    # ...and that it actually sets the inset.
    after = css[css.index(rule):css.index(rule) + 200]
    assert "margin-top" in after


# ── Settings dialog wiring ───────────────────────────────────────────────────

def _auth_src() -> str:
    return (REPO / "ui" / "auth.py").read_text(encoding="utf-8")


def test_settings_card_exists():
    src = _auth_src()
    assert 'key="stg_card_pan_enabled"' in src
    assert "temp_panopto_globally_enabled" in src


def test_toggle_participates_in_unsaved_change_detection():
    """Without this the dialog would discard the change with no warning, since
    closing Settings deliberately drops staged edits."""
    src = _auth_src()
    assert "('temp_panopto_globally_enabled', 'panopto_globally_enabled', True, bool)" in src


def test_save_writes_the_toggle_through_the_shared_config_write():
    """One writer, one atomic write. Calling set_globally_enabled() from here
    instead would race the dialog's own write and lose one side's keys."""
    src = _auth_src()
    assert "config_data[_PAN_ENABLED_KEY] = bool(temp_pan_enabled)" in src


def test_settings_save_is_read_modify_write():
    """THE cross-module invariant.

    The Settings dialog owns canvas_downloader_settings.json, but two other
    modules keep top-level keys in it: panopto_notice_ack_version
    (shared/legal.py) and panopto_globally_enabled (panopto/settings.py).
    The handler must LOAD the existing file and mutate it. If it were ever
    rewritten to build a fresh dict, saving any unrelated setting would
    silently wipe the user's acceptable-use acknowledgement and re-prompt them.
    """
    src = _auth_src()
    save = src.index("config_data['api_url'] = st.session_state.get('api_url', '')")
    head = src[max(0, save - 1200):save]
    # The dict must come from the file, not from a bare literal at the top.
    assert "json.load" in head, (
        "the settings save no longer reads the existing config first - "
        "unrelated top-level keys (the Panopto acknowledgement) will be lost"
    )


def test_no_hardcoded_tool_id_in_the_source():
    """863 is a Canvas autoincrement key, unique to CBS. Matching on it would
    make the feature work at exactly one university and silently do nothing
    everywhere else."""
    src = (REPO / "panopto" / "institution.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    # The docstring names 863 as a counter-example; no CODE line may contain it.
    body = code.split('"""')[-1]
    assert "863" not in body
