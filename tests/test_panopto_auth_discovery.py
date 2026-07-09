"""Regression tests for the Panopto LTI handshake + discovery fallbacks.

Covers the 2026-07-09 macOS round-3 findings:

1. Loop-detection false positive: a legitimate OIDC bootstrap revisits the
   SAME (url, action) pair with FRESH state/nonce fields and must be
   re-posted. The url+action-only comparison broke the working auth bootstrap
   (every launch "landed on .../external_tools/863", 0 downloads).
2. Folder landings: some Panopto LTI configs resolve per-item launches to the
   course folder's Sessions/List.aspx (30/36 CBS links). The launch must
   surface the folder id so discovery can enumerate the folder and resolve
   each link by recording title.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import panopto.auth as pauth
import panopto.discovery as pdisc

GUID_A = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0001"
GUID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0002"
GUID_C = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0003"
FOLDER = "12345678-90ab-cdef-1234-567890abcdef"


# ── fake HTTP layer for lti_launch ───────────────────────────────────────────

class _FakeResp:
    def __init__(self, url, text="", json_data=None):
        self.url = url
        self.text = text
        self._json = json_data or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class _FakeSession:
    """Plays back a scripted list of responses for session.get/post calls."""

    def __init__(self, script):
        self.headers = {}
        self._script = list(script)
        self.posts = []

    def get(self, url, **kw):
        return self._script.pop(0)

    def post(self, url, data=None, **kw):
        self.posts.append((url, dict(data or {})))
        return self._script.pop(0)


def _patch_http(monkeypatch, session, launch_url="https://canvas.test/launch"):
    fake_requests = types.SimpleNamespace(
        get=lambda url, **kw: _FakeResp(url, json_data={"url": launch_url}),
        Session=lambda: session,
    )
    monkeypatch.setattr(pauth, "requests", fake_requests)


def _form(action, **fields):
    inputs = "".join(
        f"<input type='hidden' name=\"{k}\" value=\"{v}\"/>" for k, v in fields.items()
    )
    return f"<form action=\"{action}\" method='post'>{inputs}</form>"


# ── 1. loop-detect must tolerate same (url, action) with fresh fields ────────

def test_lti_launch_reposts_same_action_with_fresh_fields(monkeypatch):
    tool_page = "https://canvas.test/courses/1/external_tools/863"
    oidc = "https://pan.panopto.test/Panopto/oidc"
    viewer = f"https://pan.panopto.test/Panopto/Pages/Viewer.aspx?id={GUID_A}"

    session = _FakeSession([
        # GET launch -> tool page, form to Panopto OIDC (state=1)
        _FakeResp(tool_page, _form(oidc, state="1")),
        # POST #1 bounces BACK to the same tool page, same action, NEW state.
        # The old (url, action)-only loop-detect broke here (the regression).
        _FakeResp(tool_page, _form(oidc, state="2")),
        # POST #2 completes the handshake and lands on the viewer.
        _FakeResp(viewer, ""),
    ])
    _patch_http(monkeypatch, session)

    s, final_url, vid, base, folder = pauth.lti_launch(
        "https://canvas.test/api/sessionless_launch", "tok")

    assert len(session.posts) == 2          # both rounds were posted
    assert vid == GUID_A
    assert base == "https://pan.panopto.test"
    assert folder is None


def test_lti_launch_breaks_on_identical_reserve(monkeypatch):
    """A page re-served IDENTICALLY (same url, action AND fields) is a dead
    loop: exactly one re-post is allowed, then the chain stops."""
    stuck = "https://canvas.test/courses/1/external_tools/863"
    oidc = "https://pan.panopto.test/Panopto/oidc"
    page = _FakeResp(stuck, _form(oidc, state="same"))

    session = _FakeSession([page, page, page, page, page])
    _patch_http(monkeypatch, session)

    s, final_url, vid, base, folder = pauth.lti_launch(
        "https://canvas.test/api/sessionless_launch", "tok")

    assert len(session.posts) == 2          # first post + one identical retry
    assert vid is None and base is None


def test_lti_launch_folder_landing_self_post_breaks(monkeypatch):
    """Landing on Sessions/List.aspx (self-posting UI form) must stop the
    chain immediately and surface the folder id from the page body."""
    list_page = "https://pan.panopto.test/Panopto/Pages/Sessions/List.aspx"
    body = _form("./List.aspx", query="") + f'<script>"folderId": "{FOLDER}"</script>'

    session = _FakeSession([_FakeResp(list_page, body)])
    _patch_http(monkeypatch, session)

    s, final_url, vid, base, folder = pauth.lti_launch(
        "https://canvas.test/api/sessionless_launch", "tok")

    assert session.posts == []              # never posts a self-form
    assert vid is None
    assert base == "https://pan.panopto.test"
    assert folder == FOLDER


# ── 2. folder-id extraction ──────────────────────────────────────────────────

def test_extract_folder_id_from_encoded_fragment():
    url = ("https://pan.panopto.test/Panopto/Pages/Sessions/List.aspx"
           f"#folderID=%22{FOLDER}%22")
    assert pauth.extract_panopto_folder_id(url) == FOLDER


def test_extract_folder_id_from_body_config():
    body = f'var cfg = {{"folderId": "{FOLDER.upper()}"}};'
    assert pauth.extract_panopto_folder_id("https://pan.panopto.test/x", body) == FOLDER


def test_extract_folder_id_none_when_absent():
    assert pauth.extract_panopto_folder_id("https://pan.panopto.test/x", "no ids") is None


# ── 3. title matching against a folder's session list ────────────────────────

_SESSIONS = [
    (GUID_A, "Video (1): kultur"),
    (GUID_B, "Video (2): kultur"),
    (GUID_C, "Helt andet oplaeg"),
]


def test_title_match_exact_normalized():
    assert pdisc._match_session_by_title("  video (1):   KULTUR ", _SESSIONS, {}) == GUID_A


def test_title_match_skips_taken_sessions_pairwise():
    taken = {GUID_A: object()}
    assert pdisc._match_session_by_title("Video (1): kultur", _SESSIONS, taken) is None
    # ...but an exact match on the OTHER recording still resolves.
    assert pdisc._match_session_by_title("Video (2): kultur", _SESSIONS, taken) == GUID_B


def test_title_match_unique_containment_only():
    # "Helt andet" is contained in exactly one session name -> accepted.
    assert pdisc._match_session_by_title(
        "Helt andet oplaeg Thursday recording", _SESSIONS, {}) == GUID_C
    # Ambiguous containment ("kultur" hits two) -> refused, never a guess.
    assert pdisc._match_session_by_title("kultur", _SESSIONS, {}) is None


def test_title_match_alnum_tier_bridges_separator_differences():
    # Underscores vs spaces vs punctuation between the module-item title and
    # the Panopto session name must still resolve (exact alnum tier).
    sessions = [(GUID_A, "Uformelle traek organisationskultur (1)")]
    assert pdisc._match_session_by_title(
        "Uformelle_traek organisationskultur 1", sessions, {}) == GUID_A


# ── 3b. folder enumeration falls back to Data.svc/GetSessions ────────────────

class _FakeHttpResp:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


class _FakeFolderSession:
    """api/v1 rejected (401), Data.svc/GetSessions answers - the CBS shape."""

    def __init__(self):
        self.posts = []

    def get(self, url, **kw):
        return _FakeHttpResp(401, text="Unauthorized")

    def post(self, url, json=None, **kw):
        self.posts.append((url, json))
        return _FakeHttpResp(200, json_data={"d": {
            "TotalNumber": 2,
            "Results": [
                {"DeliveryID": GUID_A.upper(), "SessionName": "Video (1): kultur"},
                {"DeliveryID": GUID_B, "SessionName": "Video (2): kultur"},
            ],
        }})


def test_folder_sessions_fall_back_to_data_svc():
    sess = _FakeFolderSession()
    found = pdisc._discover_folder_sessions(sess, "https://pan.panopto.test", FOLDER)
    assert found == [(GUID_A, "Video (1): kultur"), (GUID_B, "Video (2): kultur")]
    (url, payload), = sess.posts
    assert url.endswith("/Panopto/Services/Data.svc/GetSessions")
    assert payload["queryParameters"]["folderID"] == FOLDER


# ── 4. discovery wiring: folder landing resolves module links by title ───────

def test_discovery_folder_landing_resolves_links_by_title(monkeypatch):
    modules = [{
        "id": 1,
        "name": "Tema 2",
        "items": [
            {"id": 11, "title": "Video (1): kultur", "type": "ExternalTool"},
            {"id": 12, "title": "Video (2): kultur", "type": "ExternalTool"},
            {"id": 13, "title": "Findes ikke i mappen", "type": "ExternalTool"},
        ],
    }]

    class _FakeREST:
        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            return modules if path.endswith("/modules") else []

        def get_one(self, path):
            return {"url": f"https://canvas.test/api/sessionless_launch?item={path}"}

    fetches = []

    def _fake_lti(url, token):
        return (object(), "https://pan.panopto.test/Panopto/Pages/Sessions/List.aspx",
                None, "https://pan.panopto.test", FOLDER)

    def _fake_folder_sessions(session, base, folder_id):
        fetches.append(folder_id)
        return _SESSIONS

    monkeypatch.setattr(pdisc, "_CanvasREST", _FakeREST)
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)
    monkeypatch.setattr(pdisc, "_discover_folder_sessions", _fake_folder_sessions)

    videos = pdisc.discover_course_videos("https://canvas.test", "tok", 1)

    by_id = {v.video_id: v for v in videos}
    assert set(by_id) == {GUID_A, GUID_B}   # matched by title; no folder dump
    assert fetches == [FOLDER]              # folder enumerated exactly ONCE
    assert by_id[GUID_A].title == "Video (1): kultur"
    assert by_id[GUID_A].module_name == "Tema 2"
    assert by_id[GUID_A].module_item_id == 11
    assert by_id[GUID_B].module_item_id == 12
    assert all(v.source == "module" for v in videos)
    # Every video carries the VERIFIED auth beacon so the runner's session
    # bootstrap never depends on a legacy item's dead launch URL.
    assert all("sessionless_launch" in v.auth_launch_url for v in videos)
