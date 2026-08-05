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
        if url.endswith("/GetFolders"):
            return _FakeHttpResp(200, json_data={"d": {"Results": []}})
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
    session_posts = [(u, p) for u, p in sess.posts if u.endswith("/GetSessions")]
    assert session_posts
    url, payload = session_posts[0]
    assert url.endswith("/Panopto/Services/Data.svc/GetSessions")
    assert payload["queryParameters"]["folderID"] == FOLDER


SUBFOLDER = "12345678-90ab-cdef-1234-567890abcd99"


class _FakeTreeSession:
    """A course folder whose recordings live entirely in ONE subfolder -
    GetSessions on the root truthfully answers 0 (the 2026-07-09 CBS shape)."""

    def __init__(self):
        self.posts = []

    def get(self, url, **kw):
        return _FakeHttpResp(401, text="Unauthorized")

    def post(self, url, json=None, **kw):
        self.posts.append((url, json))
        qp = (json or {}).get("queryParameters") or {}
        if url.endswith("/GetFolders"):
            if qp.get("parentFolderID") == FOLDER:
                return _FakeHttpResp(200, json_data={"d": {"Results": [
                    {"ID": SUBFOLDER.upper(), "Name": "Forelaesninger"},
                ]}})
            return _FakeHttpResp(200, json_data={"d": {"Results": []}})
        if url.endswith("/GetSessions"):
            if qp.get("folderID") == SUBFOLDER:
                return _FakeHttpResp(200, json_data={"d": {
                    "TotalNumber": 2,
                    "Results": [
                        {"DeliveryID": GUID_A, "SessionName": "Video (1): kultur"},
                        {"DeliveryID": GUID_B, "SessionName": "Video (2): kultur"},
                    ],
                }})
            return _FakeHttpResp(200, json_data={"d": {"TotalNumber": 0, "Results": []}})
        return _FakeHttpResp(404, text="unexpected")


def test_folder_enumeration_walks_subfolders():
    """Sessions parked in subfolders must be found: GetSessions only lists a
    folder's DIRECT children, so the walk has to recurse via GetFolders."""
    sess = _FakeTreeSession()
    found = pdisc._discover_folder_sessions(sess, "https://pan.panopto.test", FOLDER)
    assert found == [(GUID_A, "Video (1): kultur"), (GUID_B, "Video (2): kultur")]


def test_empty_enumeration_fires_folder_probes():
    """A fully-empty walk must fire the decisive probes: GetFolderInfo (is the
    folder visible at all?) and an UNSCOPED GetSessions (does the session hold
    ANY content grants?)."""

    class _EmptySession:
        def __init__(self):
            self.posts = []

        def get(self, url, **kw):
            return _FakeHttpResp(401, text="Unauthorized")

        def post(self, url, json=None, **kw):
            self.posts.append((url, json))
            if url.endswith("/GetFolderInfo"):
                return _FakeHttpResp(200, json_data={"d": {
                    "Name": "Kursusmappe", "SessionCount": 36,
                }})
            if url.endswith("/GetFolders"):
                return _FakeHttpResp(200, json_data={"d": {"Results": []}})
            return _FakeHttpResp(200, json_data={"d": {"TotalNumber": 0, "Results": []}})

    sess = _EmptySession()
    found = pdisc._discover_folder_sessions(sess, "https://pan.panopto.test", FOLDER)
    assert found == []
    called = {u.rsplit("/", 1)[-1] for u, _p in sess.posts}
    assert "GetFolderInfo" in called
    unscoped = [p for u, p in sess.posts
                if u.endswith("/GetSessions")
                and p["queryParameters"]["folderID"] is None]
    assert unscoped, "the unscoped auth probe never ran"


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


# ── 5. stale direct GUIDs are remapped by title against the folder ───────────

def test_stale_module_ids_remap_to_folder_sessions(monkeypatch):
    """A module item can embed a delivery GUID that no longer exists after a
    Panopto migration (DeliveryInfo answers "session isn't available" for it).
    Once the course folder has been enumerated, the stale id must be remapped
    to the live session with the matching title."""
    STALE = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff9999"
    modules = [{
        "id": 1,
        "name": "Tema 2",
        "items": [
            {"id": 11, "title": "Video (1): kultur", "type": "ExternalTool",
             "external_url": ("https://pan.panopto.test/Panopto/Pages/"
                              f"Viewer.aspx?id={STALE}")},
            {"id": 12, "title": "Helt andet oplaeg", "type": "ExternalTool"},
        ],
    }]

    class _FakeREST:
        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            return modules if path.endswith("/modules") else []

        def get_one(self, path):
            return {"url": f"https://canvas.test/api/sessionless_launch?item={path}"}

    def _fake_lti(url, token):
        return (object(), "https://pan.panopto.test/Panopto/Pages/Sessions/List.aspx",
                None, "https://pan.panopto.test", FOLDER)

    monkeypatch.setattr(pdisc, "_CanvasREST", _FakeREST)
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)
    monkeypatch.setattr(pdisc, "_discover_folder_sessions",
                        lambda *a, **k: _SESSIONS)

    videos = pdisc.discover_course_videos("https://canvas.test", "tok", 1)

    by_id = {v.video_id: v for v in videos}
    assert STALE not in by_id                       # dead id healed away
    assert by_id[GUID_A].title == "Video (1): kultur"
    assert by_id[GUID_A].module_item_id == 11       # identity preserved
    assert by_id[GUID_C].module_item_id == 12       # folder-matched neighbour


# ── 6. LTI 1.3 module-item launches (2026-07-09 CBS migration) ───────────────

def test_lti_launch_ignores_panopto_markers_on_canvas_hops(monkeypatch):
    """An intermediate Canvas hop (/api/lti/authorize) carries the encoded
    Panopto target - including a legacy custom_context_delivery GUID - in its
    QUERY. The chain must keep posting until the URL's HOST is Panopto, or it
    breaks one hop early ("break:viewer" on a Canvas URL, no cookies)."""
    tool_page = "https://canvas.test/courses/1/external_tools/863"
    oidc = "https://pan.panopto.test/Panopto/lti/adv/platforms/x/login"
    authorize = ("https://canvas.test/api/lti/authorize?redirect_uri="
                 "https%3A%2F%2Fpan.panopto.test%2FPanopto%2FLTI%2FLTI.aspx"
                 f"&custom_context_delivery={GUID_B}")
    lti_aspx = "https://pan.panopto.test/Panopto/LTI/LTI.aspx"
    viewer = f"https://pan.panopto.test/Panopto/Pages/Viewer.aspx?id={GUID_A}"

    session = _FakeSession([
        _FakeResp(tool_page, _form(oidc, login_hint="h")),
        _FakeResp(authorize, _form(lti_aspx, id_token="jwt", state="s")),
        _FakeResp(viewer, ""),
    ])
    _patch_http(monkeypatch, session)

    s, final_url, vid, base, folder = pauth.lti_launch(
        "https://canvas.test/api/sessionless_launch", "tok")

    assert len(session.posts) == 2   # the authorize hop was POSTED, not broken on
    assert vid == GUID_A             # the LIVE id from the viewer, never GUID_B
    assert base == "https://pan.panopto.test"


def test_discovery_module_item_launch_resolves_bare_lti13_links(monkeypatch):
    """LTI 1.3 deep links carry NO GUID anywhere in the item JSON (bare
    LTI.aspx external_url); only the per-item module-item launch
    (launch_type=module_item) resolves the session. The item's own generic
    launch URL lands on the course folder and must not be used."""
    modules = [{
        "id": 1, "name": "Tema 1",
        "items": [{
            "id": 11, "title": "Video (1): kultur", "type": "ExternalTool",
            "content_id": 863,
            "url": ("https://canvas.test/api/v1/courses/1/external_tools/"
                    "sessionless_launch?id=863&url=LTI.aspx"),
            "external_url": "https://pan.panopto.test/Panopto/LTI/LTI.aspx",
        }],
    }]

    class _FakeREST:
        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            return modules if path.endswith("/modules") else []

        def get_one(self, path):
            raise AssertionError("detail fetch must be skipped when the "
                                 "module-item launch resolves the session")

    launched = []

    def _fake_lti(url, token):
        launched.append(url)
        assert "launch_type=module_item&module_item_id=11" in url
        assert "&id=863" in url
        return (object(),
                f"https://pan.panopto.test/Panopto/Pages/Embed.aspx?id={GUID_A}",
                GUID_A, "https://pan.panopto.test", None)

    monkeypatch.setattr(pdisc, "_CanvasREST", _FakeREST)
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)

    videos = pdisc.discover_course_videos("https://canvas.test", "tok", 1)

    assert [v.video_id for v in videos] == [GUID_A]
    assert len(launched) == 1
    assert "launch_type=module_item" in videos[0].launch_url
    assert videos[0].auth_launch_url == videos[0].launch_url
    assert videos[0].module_item_id == 11


def test_discovery_launch_resolution_beats_embedded_stale_guid(monkeypatch):
    """A legacy item embeds custom_context_delivery=<stale guid>; after an LTI
    migration that id is dead while the module-item launch resolves the LIVE
    session. Only the live id may survive (a dead id would download nothing,
    a re-homed one the WRONG recording)."""
    STALE = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff9999"
    modules = [{
        "id": 1, "name": "Tema 1",
        "items": [{
            "id": 11, "title": "Video (1): kultur", "type": "ExternalTool",
            "content_id": 863,
            "external_url": ("https://pan.panopto.test/Panopto/LTI/LTI.aspx"
                             f"?custom_context_delivery={STALE}"),
        }],
    }]

    class _FakeREST:
        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            return modules if path.endswith("/modules") else []

        def get_one(self, path):
            return {}

    def _fake_lti(url, token):
        assert "launch_type=module_item" in url
        return (object(),
                f"https://pan.panopto.test/Panopto/Pages/Viewer.aspx?id={GUID_A}",
                GUID_A, "https://pan.panopto.test", None)

    monkeypatch.setattr(pdisc, "_CanvasREST", _FakeREST)
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)

    videos = pdisc.discover_course_videos("https://canvas.test", "tok", 1)

    by_id = {v.video_id: v for v in videos}
    assert set(by_id) == {GUID_A}           # stale id dropped, live id kept
    assert by_id[GUID_A].module_item_id == 11


def test_discovery_falls_back_to_embedded_guid_when_launch_fails(monkeypatch):
    """When the module-item launch cannot reach Panopto at all, the embedded
    GUID (pre-1.3 style) must still be used - old behavior preserved."""
    modules = [{
        "id": 1, "name": "Tema 1",
        "items": [{
            "id": 11, "title": "Video (1): kultur", "type": "ExternalTool",
            "external_url": ("https://pan.panopto.test/Panopto/Pages/"
                             f"Viewer.aspx?id={GUID_A}"),
        }],
    }]

    class _FakeREST:
        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            return modules if path.endswith("/modules") else []

        def get_one(self, path):
            return {}

    def _fake_lti(url, token):
        return (None, None, None, None, None)      # hard failure

    monkeypatch.setattr(pdisc, "_CanvasREST", _FakeREST)
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)

    videos = pdisc.discover_course_videos("https://canvas.test", "tok", 1)
    assert [v.video_id for v in videos] == [GUID_A]


# ── 7. log hygiene: auth diagnostics + HTML-free error messages ──────────────

def test_session_auth_diag_reports_cookie_names_and_markers():
    import requests

    s = requests.Session()
    s.cookies.set(".ASPXAUTH", "secretvalue", domain="pan.panopto.test")
    s.cookies.set("csrfToken", "x", domain="pan.panopto.test")
    s.cookies.set("canvas_session", "y", domain="canvas.test")
    body = ('{"IsAuthenticated": false} '
            '<a href="/Panopto/Pages/Auth/Login.aspx">Log in</a>')

    diag = pauth._session_auth_diag(s, "https://pan.panopto.test", body)

    assert ".ASPXAUTH" in diag and "csrfToken" in diag   # names, host-matched
    assert "canvas_session" not in diag                  # foreign host excluded
    assert "secretvalue" not in diag                     # never values
    assert "IsAuthenticated=false" in diag
    assert "login-link-present" in diag


def test_delivery_error_messages_are_html_stripped():
    from panopto.stream import _clean_error

    raw = ("This session isn't available. It may have been deleted.<br>"
           "<a href='/Panopto/Pages/Sessions/List.aspx'>See other videos</a>")
    cleaned = _clean_error(raw)
    assert "<" not in cleaned and ">" not in cleaned
    assert cleaned == ("This session isn't available. It may have been "
                       "deleted. See other videos")


# ── 8. vanity / on-prem host detection ───────────────────────────────────────
#
# An institution can front Panopto with a vanity CNAME (video.university.edu) or
# self-host it on a fully custom domain - the hostname then carries no "panopto"
# at all, but the "/Panopto/" product route in the PATH does. Matching only the
# host used to return panopto_base=None for these tenants, so the runner
# concluded "no Panopto session" and every download failed even though the LTI
# session was valid. Detection must key off host OR the /Panopto/ route, and must
# never fire on the query string (a Canvas OIDC hop carries the encoded Panopto
# target in redirect_uri).

def test_panopto_base_from_cloud_hosts():
    # US and EU cloud tenants, plus a plain panopto.<uni> host: matched by host.
    assert (pauth.panopto_base_from_url(
        f"https://cbs.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id={GUID_A}")
        == "https://cbs.hosted.panopto.com")
    assert (pauth.panopto_base_from_url(
        f"https://uni.cloud.panopto.eu/Panopto/Pages/Embed.aspx?id={GUID_A}")
        == "https://uni.cloud.panopto.eu")
    assert (pauth.panopto_base_from_url(
        "https://panopto.university.edu/Panopto/Pages/Sessions/List.aspx")
        == "https://panopto.university.edu")


def test_panopto_base_from_vanity_and_onprem_hosts():
    # THE FIX: host carries no "panopto"; the /Panopto/ route in the PATH is the
    # only signal. Both a vanity CNAME and an on-prem custom domain must resolve.
    assert (pauth.panopto_base_from_url(
        f"https://video.university.edu/Panopto/Pages/Viewer.aspx?id={GUID_A}")
        == "https://video.university.edu")
    assert (pauth.panopto_base_from_url(
        "https://lecturecapture.uni.ac.uk/Panopto/Pages/Embed.aspx"
        f"?id={GUID_A}&v=1")
        == "https://lecturecapture.uni.ac.uk")
    # Case-insensitive on the route, and a reverse-proxy path prefix is tolerated.
    assert (pauth.panopto_base_from_url(
        "https://media.uni.edu/lms/panopto/Pages/Viewer.aspx")
        == "https://media.uni.edu")


def test_panopto_base_ignores_panopto_in_query_only():
    # A Canvas OIDC/authorize hop carries the encoded Panopto target in its
    # QUERY, not its path. It is NOT a Panopto landing - matching it here would
    # break the handshake one hop early (the regression guarded in test #6).
    authorize = ("https://canvas.university.edu/api/lti/authorize?redirect_uri="
                 "https%3A%2F%2Fvideo.uni.edu%2FPanopto%2FLTI%2FLTI.aspx"
                 f"&custom_context_delivery={GUID_B}")
    assert pauth.panopto_base_from_url(authorize) is None


def test_panopto_base_none_for_non_panopto_and_garbage():
    # A vanity host OUTSIDE the /Panopto/ route (e.g. its SSO login page) is not
    # yet a Panopto landing; unrelated hosts and junk are never Panopto.
    assert pauth.panopto_base_from_url(
        "https://video.university.edu/idp/login?target=x") is None
    assert pauth.panopto_base_from_url("https://canvas.university.edu/courses/1") is None
    # "panopto" as a mere path substring on an unrelated host is not the route.
    assert pauth.panopto_base_from_url("https://example.com/panoptolike/thing") is None
    assert pauth.panopto_base_from_url("") is None
    assert pauth.panopto_base_from_url(None) is None
    assert pauth.panopto_base_from_url("not a url") is None


def test_lti_launch_resolves_on_vanity_host(monkeypatch):
    """End-to-end: an institution whose Panopto host carries no "panopto" (a
    vanity CNAME) must complete the handshake and hand the runner a usable
    session, base and id. Before the path-marker fix this returned base=None and
    the whole course failed with 'no Panopto session' despite valid cookies."""
    tool_page = "https://canvas.university.edu/courses/1/external_tools/42"
    vanity_oidc = "https://video.university.edu/Panopto/oidc"
    vanity_viewer = (
        f"https://video.university.edu/Panopto/Pages/Viewer.aspx?id={GUID_A}")

    session = _FakeSession([
        # GET launch -> Canvas tool page (host has no "panopto", path is not the
        # product route) -> must NOT be treated as terminal; post the form.
        _FakeResp(tool_page, _form(vanity_oidc, state="1")),
        # POST lands on the vanity Panopto viewer: host has no "panopto" either,
        # only the /Panopto/ path proves it. This is the hop that used to fail.
        _FakeResp(vanity_viewer, ""),
    ])
    _patch_http(monkeypatch, session)

    s, final_url, vid, base, folder = pauth.lti_launch(
        "https://canvas.university.edu/api/sessionless_launch", "tok")

    assert len(session.posts) == 1              # tool page posted, not broken on
    assert vid == GUID_A
    assert base == "https://video.university.edu"
    assert folder is None
    assert s is session                         # the authed session is returned


def test_lti_launch_vanity_folder_landing_surfaces_folder_id(monkeypatch):
    """A vanity host whose per-item launch lands on the self-posting course
    session list must break on the self-post and surface the folder id - the
    same folder-landing discovery path cloud hosts get, previously unreachable
    for vanity tenants (the host was never recognised as Panopto)."""
    list_page = "https://video.university.edu/Panopto/Pages/Sessions/List.aspx"
    body = _form("./List.aspx", query="") + f'<script>"folderId": "{FOLDER}"</script>'

    session = _FakeSession([_FakeResp(list_page, body)])
    _patch_http(monkeypatch, session)

    s, final_url, vid, base, folder = pauth.lti_launch(
        "https://canvas.university.edu/api/sessionless_launch", "tok")

    assert session.posts == []                  # never posts the self-form
    assert vid is None
    assert base == "https://video.university.edu"
    assert folder == FOLDER


# ── 9. course-folder fallback: nav-tab-only courses + multiple deployments ────
#
# A course can link recordings ONLY through the course-level Panopto navigation
# tab / a linked folder, with no module item, page, assignment or announcement to
# key off. The content scan then finds nothing to launch and the folder is never
# enumerated - so such a course used to yield ZERO recordings. In folder scope,
# discovery now launches the Panopto tool at COURSE level and enumerates the
# course folder directly, trying every deployment a multi-deployment campus
# exposes.

def test_course_level_launch_urls_one_per_deployment(monkeypatch):
    """A multiple-deployment campus exposes more than one Panopto tool id; the
    fallback must offer a launch for EACH (sorted), so the caller can try every
    deployment - a course belongs to one and Canvas doesn't say which."""
    import panopto.institution as pinst
    scan = pinst.ToolScan(resolved=True, has_panopto=True,
                          panopto_tool_ids=frozenset({77, 42}),
                          known_tool_ids=frozenset({77, 42, 9}))
    monkeypatch.setattr(pinst, "cached_scan", lambda rest, cid: scan)

    class _Rest:
        base = "https://canvas.university.edu"

    urls = pdisc.course_level_launch_urls(_Rest(), 55)
    assert urls == [
        "https://canvas.university.edu/api/v1/courses/55/external_tools/"
        "sessionless_launch?id=42",
        "https://canvas.university.edu/api/v1/courses/55/external_tools/"
        "sessionless_launch?id=77",
    ]
    # The singular helper keeps returning the first (the last-resort beacon).
    assert pdisc.course_level_launch_url(_Rest(), 55) == urls[0]


def test_course_level_launch_urls_empty_without_panopto(monkeypatch):
    """No Panopto tool -> no launch URLs, so the caller falls back to "no
    session" exactly as before (never a blind launch of an unknown tool)."""
    import panopto.institution as pinst
    monkeypatch.setattr(pinst, "cached_scan",
                        lambda rest, cid: pinst.ToolScan(resolved=True))

    class _Rest:
        base = "https://canvas.university.edu"

    assert pdisc.course_level_launch_urls(_Rest(), 1) == []
    assert pdisc.course_level_launch_url(_Rest(), 1) == ""


def _nav_tab_only_rest():
    """A course with NO module items and no page/assignment/announcement embeds -
    every content endpoint answers empty."""
    class _FakeREST:
        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            return []

        def get_one(self, path):
            return {}

    return _FakeREST


def test_discovery_course_folder_fallback_enumerates_nav_tab_only_course(monkeypatch):
    """The whole course folder is discovered from a course-level launch even when
    nothing in the course content links a single recording."""
    launched = []

    def _fake_lti(url, token):
        launched.append(url)
        return (object(),
                "https://pan.panopto.test/Panopto/Pages/Sessions/List.aspx",
                None, "https://pan.panopto.test", FOLDER)

    enumerated = []

    def _fake_folder_sessions(session, base, folder_id):
        enumerated.append(folder_id)
        return _SESSIONS

    monkeypatch.setattr(pdisc, "_CanvasREST", _nav_tab_only_rest())
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)
    monkeypatch.setattr(pdisc, "_discover_folder_sessions", _fake_folder_sessions)
    monkeypatch.setattr(pdisc, "course_level_launch_urls",
                        lambda rest, cid: [
                            "https://canvas.test/api/v1/courses/1/external_tools/"
                            "sessionless_launch?id=863"])

    videos = pdisc.discover_course_videos(
        "https://canvas.test", "tok", 1, include_folder_sessions=True)

    by_id = {v.video_id: v for v in videos}
    assert set(by_id) == {GUID_A, GUID_B, GUID_C}   # the whole folder
    assert enumerated == [FOLDER]                    # course folder, enumerated once
    assert all(v.source == "folder" for v in videos)
    # These recordings carry no launch URL of their own; the working course-level
    # launch becomes their auth beacon so the runner can still authenticate.
    assert all("sessionless_launch" in v.auth_launch_url for v in videos)


def test_course_folder_fallback_tries_every_deployment(monkeypatch):
    """On a multi-deployment campus the first deployment may not resolve the
    course folder; the fallback must try the next until one does, and adopt the
    working launch as the beacon."""
    DEAD = ("https://canvas.test/api/v1/courses/1/external_tools/"
            "sessionless_launch?id=10")
    LIVE = ("https://canvas.test/api/v1/courses/1/external_tools/"
            "sessionless_launch?id=20")

    def _fake_lti(url, token):
        if url == DEAD:
            return (None, None, None, None, None)      # deployment 10: no session
        return (object(),
                "https://pan.panopto.test/Panopto/Pages/Sessions/List.aspx",
                None, "https://pan.panopto.test", FOLDER)

    monkeypatch.setattr(pdisc, "_CanvasREST", _nav_tab_only_rest())
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)
    monkeypatch.setattr(pdisc, "_discover_folder_sessions",
                        lambda *a, **k: _SESSIONS)
    monkeypatch.setattr(pdisc, "course_level_launch_urls",
                        lambda rest, cid: [DEAD, LIVE])

    videos = pdisc.discover_course_videos(
        "https://canvas.test", "tok", 1, include_folder_sessions=True)

    assert {v.video_id for v in videos} == {GUID_A, GUID_B, GUID_C}
    # The working deployment's launch is the beacon, never the dead one.
    assert all(v.auth_launch_url == LIVE for v in videos)


def test_course_folder_fallback_skipped_when_a_folder_already_enumerated(monkeypatch):
    """A course whose module items already landed on (and enumerated) their
    folder must NOT pay for a second course-level launch: the guard is an empty
    folder-sessions cache."""
    modules = [{
        "id": 1, "name": "Tema 2",
        "items": [{"id": 11, "title": "Video (1): kultur", "type": "ExternalTool"}],
    }]

    class _FakeREST:
        def __init__(self, *a, **k):
            pass

        def get_all(self, path, params=None):
            return modules if path.endswith("/modules") else []

        def get_one(self, path):
            return {"url": f"https://canvas.test/api/sessionless_launch?item={path}"}

    def _fake_lti(url, token):
        # The module item lands on the course folder (folder-landing shape).
        return (object(), "https://pan.panopto.test/Panopto/Pages/Sessions/List.aspx",
                None, "https://pan.panopto.test", FOLDER)

    course_level_calls = []

    def _spy_course_urls(rest, cid):
        course_level_calls.append(cid)
        return ["https://canvas.test/x/sessionless_launch?id=863"]

    monkeypatch.setattr(pdisc, "_CanvasREST", _FakeREST)
    monkeypatch.setattr(pdisc, "lti_launch", _fake_lti)
    monkeypatch.setattr(pdisc, "_discover_folder_sessions", lambda *a, **k: _SESSIONS)
    monkeypatch.setattr(pdisc, "course_level_launch_urls", _spy_course_urls)

    videos = pdisc.discover_course_videos(
        "https://canvas.test", "tok", 1, include_folder_sessions=True)

    assert {v.video_id for v in videos}                # folder was expanded
    assert course_level_calls == []                    # fallback never fired


def test_course_folder_fallback_not_in_directly_linked_scope(monkeypatch):
    """Outside folder scope (include_folder_sessions=False) the fallback must
    NOT run - that mode returns only directly-linked recordings, never a folder
    dump."""
    called = []
    monkeypatch.setattr(pdisc, "_CanvasREST", _nav_tab_only_rest())
    monkeypatch.setattr(pdisc, "course_level_launch_urls",
                        lambda rest, cid: called.append(cid) or ["x"])

    videos = pdisc.discover_course_videos("https://canvas.test", "tok", 1)

    assert videos == []
    assert called == []
