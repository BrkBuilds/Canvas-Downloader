"""Discover Panopto recordings linked in a Canvas course.

Scans modules, pages, assignments and announcements via the Canvas REST API
(reusing the logged-in token + resolved base URL) and extracts Panopto video
GUIDs. ExternalTool launch links are resolved through the LTI handshake.

Parametrized by Canvas base + token (no hardcoded institution). Returns a list
of ``PanoptoVideo`` records, de-duplicated by video id.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

from panopto.auth import (
    PANOPTO_FOLDER_PATTERN, extract_panopto_ids, lti_launch,
)

logger = logging.getLogger(__name__)


def _norm_title(s: str) -> str:
    """Whitespace-collapsed, casefolded title for session-name matching."""
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def _norm_alnum(s: str) -> str:
    """Only letters/digits, casefolded - bridges '_' vs ' ' vs punctuation
    divergence between a module-item title and the Panopto session name
    (e.g. 'Uformelletræk_organisationskultur' vs 'Uformelle træk organisationskultur'
    differ only in separators)."""
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())


def _match_session_by_title(title: str, sessions, taken) -> str | None:
    """Resolve a module-item *title* against a folder's ``(id, name)`` sessions.

    Institutions that insert Panopto deep links name the module item after the
    recording, so an exact (normalized) name match is the norm. Sessions whose
    id is already attributed (*taken*) are excluded first, which lets two
    same-named recordings matched by two same-named items resolve pairwise in
    folder order. Tiers: exact normalized -> exact alphanumeric-only (separator
    and punctuation differences) -> containment, accepted only when UNIQUE so
    a generic title can never grab an arbitrary recording.
    """
    want = _norm_title(title)
    if not want:
        return None
    available = [(vid, _norm_title(name)) for vid, name in sessions if vid not in taken]
    exact = [vid for vid, name in available if name == want]
    if exact:
        return exact[0]
    want_an = _norm_alnum(title)
    if want_an:
        exact_an = [vid for vid, name in available if _norm_alnum(name) == want_an]
        if exact_an:
            return exact_an[0]
    contains = [vid for vid, name in available
                if name and (name in want or want in name)]
    if len(contains) == 1:
        return contains[0]
    return None


@dataclass
class PanoptoVideo:
    video_id: str                 # Panopto GUID (lowercased)
    title: str                    # human-readable recording title
    module_name: str = ""         # sanitized-later module name, "" if not module-linked
    launch_url: str = ""          # Canvas sessionless_launch API url (for auth)
    source: str = "module"        # module | page | assignment | announcement | folder
    module_item_id: int = 0       # Canvas module item id (for stable manifest ids)
    # A launch URL that discovery VERIFIED reaches a Panopto host this run
    # (the auth "beacon"). Some legacy items carry launch URLs that no longer
    # complete the LTI chain (observed after CBS's LTI 1.3 migration: the six
    # old-style links' own launches die on the Canvas tool page while every
    # detail-fetched launch lands authenticated on Panopto) - the runner's
    # session bootstrap tries this validated URL FIRST.
    auth_launch_url: str = ""


class _CanvasREST:
    """Minimal Canvas REST client (token + base), mirroring the proven flow."""

    def __init__(self, base_url: str, token: str, timeout: int = 20):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout = timeout

    def get_all(self, path: str, params: dict | None = None) -> list:
        results: list = []
        url = f"{self.base}{path}"
        p = dict(params or {})
        p.setdefault("per_page", 100)
        while url:
            try:
                r = requests.get(url, headers=self.headers, params=p, timeout=self.timeout)
                r.raise_for_status()
            except requests.HTTPError as e:
                if getattr(r, "status_code", 0) != 404:
                    logger.debug(f"Canvas {path}: {e}")
                break
            except Exception as e:
                logger.debug(f"Canvas {path}: {e}")
                break
            data = r.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                return data
            url = r.links.get("next", {}).get("url")
            p = {}
        return results

    def get_one(self, path: str) -> dict:
        try:
            r = requests.get(f"{self.base}{path}", headers=self.headers, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}


def _panopto_api_get(session: requests.Session, panopto_base: str, path: str, params=None):
    """GET a Panopto api/v1 endpoint. Returns ``(json | None, status)``.

    *status* is the HTTP status code, or a short error string - callers log it
    so an access-denied API no longer fails silently (the 2026-07-09 run
    reported 'enumerated 0 session(s)' with zero clues as to why).
    """
    try:
        r = session.get(
            f"{panopto_base}/Panopto/api/v1/{path}",
            params=params or {},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json(), 200
        return None, r.status_code
    except Exception as e:
        return None, f"error: {e}"


def _folder_sessions_api_v1(session, panopto_base, folder_id) -> list[tuple[str, str]]:
    """Enumerate a folder via the modern REST API (needs api/v1 cookie access)."""
    found, page = [], 0
    while True:
        data, status = _panopto_api_get(
            session, panopto_base, f"folders/{folder_id}/sessions",
            {"pageNumber": page, "pageSize": 100, "sortField": "1", "sortOrder": "0"},
        )
        if data is None:
            if page == 0:
                logger.info(
                    "Panopto api/v1 folder listing unavailable for %s "
                    "(status %s) - will fall back to Data.svc/GetSessions.",
                    folder_id, status,
                )
            break
        results = data.get("Results", [])
        for item in results:
            vid = (item.get("Id") or "").lower()
            name = item.get("Name") or "Unnamed"
            if vid:
                found.append((vid, name))
        if len(results) < 100:
            break
        page += 1
    return found


_GUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _data_svc_post(session, panopto_base, method, payload):
    """POST a Panopto internal ``Data.svc/<method>``. Returns ``(d, note)``.

    ``d`` is the response's ``d`` node (``None`` on any failure); ``note`` is a
    one-line diagnostic (status + collapsed body snippet) so a denied or
    malformed call is explainable from debug_log.txt instead of surfacing as a
    silent 0. Requests carry the browser-parity headers (Origin/Referer/XHR
    marker) the real ``List.aspx`` sends - some ASP.NET service configs filter
    on them.
    """
    def _snippet(text, n: int = 300) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()[:n]

    try:
        r = session.post(
            f"{panopto_base}/Panopto/Services/Data.svc/{method}",
            json=payload,
            headers={
                "Accept": "application/json",
                "Origin": panopto_base,
                "Referer": f"{panopto_base}/Panopto/Pages/Sessions/List.aspx",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=30,
        )
    except Exception as e:
        return None, f"request failed: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {_snippet(r.text)}"
    try:
        d = (r.json() or {}).get("d")
    except Exception:
        return None, f"non-JSON response: {_snippet(r.text)}"
    if d is None:
        return None, f"no 'd' node: {_snippet(r.text)}"
    return d, None


def _folder_sessions_data_svc(session, panopto_base, folder_id) -> list[tuple[str, str]]:
    """Sessions sitting DIRECTLY in a folder via ``Data.svc/GetSessions``.

    This is the exact call ``Sessions/List.aspx`` itself makes to render the
    session list, so it works with the plain page cookies wherever the list
    page renders - including tenants whose ``api/v1`` rejects cookie auth
    (CBS: api/v1 401s while the list page shows all recordings). Results carry
    ``DeliveryID`` (the id DeliveryInfo wants) + ``SessionName``. NOTE: it does
    NOT include sessions inside subfolders - callers that need the whole tree
    use :func:`_discover_folder_sessions`.
    """
    found, page = [], 0
    while True:
        payload = {"queryParameters": {
            "query": None,
            "sortColumn": 1,
            "sortAscending": False,
            "maxResults": 100,
            "page": page,
            "startDate": None,
            "endDate": None,
            "folderID": folder_id,
            "bookmarked": False,
            "getFolderData": page == 0,
            "includeArchived": True,
            "includePlaylists": True,
        }}
        d, note = _data_svc_post(session, panopto_base, "GetSessions", payload)
        if d is None or not isinstance(d, dict):
            logger.info("Panopto GetSessions failed for folder %s: %s",
                        folder_id, note or f"unexpected shape {type(d).__name__}")
            break
        results = d.get("Results") or []
        for item in results:
            vid = (item.get("DeliveryID") or item.get("SessionID")
                   or item.get("Id") or "").lower()
            name = (item.get("SessionName") or item.get("Name") or "Unnamed")
            if vid:
                found.append((vid, name))
        total = d.get("TotalNumber")
        if page == 0:
            logger.info(
                "Panopto GetSessions: folder %s reports %s session(s) "
                "(page 0 returned %d).",
                folder_id, total if total is not None else "?", len(results),
            )
            if not results:
                # The full 'd' node of an empty answer is the diagnostic gold:
                # it shows WHAT Panopto thinks it returned (folder data, error
                # markers, a different result key) instead of just "0".
                import json as _json
                try:
                    logger.info("Panopto GetSessions raw 'd' node for %s: %.400s",
                                folder_id, _json.dumps(d, default=str))
                except Exception:
                    pass
        if len(results) < 100:
            break
        if isinstance(total, int) and len(found) >= total:
            break
        page += 1
    return found


def _folder_subfolders_data_svc(session, panopto_base, folder_id) -> list[tuple[str, str]]:
    """Direct subfolders of *folder_id* as ``(id, name)`` via ``Data.svc/GetFolders``.

    Course folders frequently keep their recordings in per-module/per-term
    SUBFOLDERS; ``GetSessions`` on the parent then truthfully answers 0 while
    the browser page shows everything (it renders the tree). Best-effort and
    shape-tolerant: id key spelling varies across Panopto versions, and any
    failure just logs + returns [] (the parent's own sessions still count).
    """
    payload = {"queryParameters": {
        "query": None,
        "sortColumn": 0,
        "sortAscending": True,
        "maxResults": 200,
        "page": 0,
        "parentFolderID": folder_id,
        "folderOutputType": 0,
        "onlyCanEdit": False,
        "onlySubscribed": False,
    }}
    d, note = _data_svc_post(session, panopto_base, "GetFolders", payload)
    if d is None:
        logger.info("Panopto GetFolders failed for folder %s: %s", folder_id, note)
        return []
    results = d if isinstance(d, list) else (d.get("Results") or [])
    out = []
    for item in results:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("ID") or item.get("Id")
                  or item.get("PublicID") or "").lower()
        name = item.get("Name") or "Unnamed"
        if _GUID_RE.fullmatch(fid):
            out.append((fid, name))
    return out


def _log_folder_probes(session, panopto_base, folder_id) -> None:
    """Decisive diagnostics for a folder whose whole enumeration came back 0.

    Two probes that separate the possible causes cleanly:
      * ``GetFolderInfo`` - does the session even SEE the folder (name/counts),
        or is the extracted folder id wrong/denied?
      * an UNSCOPED ``GetSessions`` (no folderID) - can the session see ANY
        content at all? ``TotalNumber=0`` here means the LTI cookie carries no
        content grants (effectively anonymous - Panopto masks missing grants
        as empty lists and "session isn't available" errors); ``>0`` means
        auth is fine and the problem is folder-scoped.
    """
    d, note = _data_svc_post(session, panopto_base, "GetFolderInfo",
                             {"folderID": folder_id})
    if isinstance(d, dict):
        logger.info(
            "Panopto GetFolderInfo probe for %s -> name=%r sessions=%s "
            "subfolders=%s",
            folder_id, d.get("Name"),
            d.get("SessionCount", "?"), d.get("ChildFolderCount", "?"),
        )
    else:
        logger.info("Panopto GetFolderInfo probe for %s -> %s",
                    folder_id, note or "unexpected shape")
    payload = {"queryParameters": {
        "query": None, "sortColumn": 1, "sortAscending": False,
        "maxResults": 1, "page": 0, "startDate": None, "endDate": None,
        "folderID": None, "bookmarked": False, "getFolderData": False,
        "includeArchived": True, "includePlaylists": True,
    }}
    d2, note2 = _data_svc_post(session, panopto_base, "GetSessions", payload)
    if isinstance(d2, dict):
        logger.info(
            "Panopto unscoped GetSessions probe -> TotalNumber=%s "
            "(0 = the Panopto session holds NO content grants at all, i.e. "
            "the LTI cookie is effectively anonymous; >0 = auth works and "
            "the problem is folder-scoped)",
            d2.get("TotalNumber"),
        )
    else:
        logger.info("Panopto unscoped GetSessions probe -> %s",
                    note2 or "unexpected shape")


def _discover_folder_sessions(session, panopto_base, folder_id) -> list[tuple[str, str]]:
    """All ``(delivery_id, name)`` sessions in *folder_id*, subfolders included.

    api/v1 first (one call, when the tenant allows cookie auth), then the
    Data.svc route the list page itself uses. ``GetSessions`` only returns the
    sessions sitting DIRECTLY in a folder, and course folders often park their
    recordings in per-module subfolders - the 2026-07-09 CBS run answered a
    truthful 0 for the course folder while the browser page showed 36. The
    Data.svc path therefore walks the subfolder tree breadth-first (bounded:
    depth <= 3, <= 40 folders) and aggregates. When the whole walk still finds
    nothing, :func:`_log_folder_probes` records the decisive facts.
    """
    found = _folder_sessions_api_v1(session, panopto_base, folder_id)
    if found:
        return found

    root = (folder_id or "").lower()
    seen = {root}
    queue: list[tuple[str, str, int]] = [(root, "", 0)]   # (id, name, depth)
    collected: list[tuple[str, str]] = []
    _MAX_DEPTH, _MAX_FOLDERS = 3, 40
    walked = 0
    while queue:
        if walked >= _MAX_FOLDERS:
            logger.info(
                "Panopto folder walk truncated at %d folder(s) "
                "(%d still queued under %s).", walked, len(queue), root)
            break
        fid, fname, depth = queue.pop(0)
        walked += 1
        sessions = _folder_sessions_data_svc(session, panopto_base, fid)
        if sessions and depth > 0:
            logger.info("Panopto subfolder '%s' (%s) adds %d session(s).",
                        fname, fid, len(sessions))
        collected.extend(sessions)
        if depth >= _MAX_DEPTH:
            continue
        for sub_id, sub_name in _folder_subfolders_data_svc(session, panopto_base, fid):
            if sub_id not in seen:
                seen.add(sub_id)
                queue.append((sub_id, sub_name, depth + 1))

    deduped, out = set(), []
    for vid, name in collected:
        if vid not in deduped:
            deduped.add(vid)
            out.append((vid, name))
    if not out:
        _log_folder_probes(session, panopto_base, root)
    return out


def discover_course_videos(
    canvas_base: str,
    token: str,
    course_id,
    *,
    include_folder_sessions: bool = False,
    is_cancelled=None,
    on_event=None,
) -> list[PanoptoVideo]:
    """Return Panopto videos linked in *course_id*.

    include_folder_sessions: when True, ExternalTool links that point at a
        Panopto folder are expanded to every session in that folder ('folder'
        discovery scope). When False, only directly-linked videos are returned.
    on_event: optional callback for live sub-progress during the (slow) scan, so
        the UI never looks frozen. Fired as:
          on_event('stage', name=str)               at each section start
          on_event('scan', detail=str)              per item examined
          on_event('video', title=str, source=str)  when a new recording is found
        Best-effort: any exception from the callback is swallowed.
    """
    rest = _CanvasREST(canvas_base, token)
    videos: dict[str, PanoptoVideo] = {}

    # Which LTI tools this institution has, so pass 2 can skip the ones that
    # provably are not Panopto. Memoised per Canvas host, so this is one ~230ms
    # lookup for the whole run rather than one per course. Any failure yields an
    # unresolved scan, which classifies nothing and therefore skips nothing.
    from panopto.institution import cached_scan
    _tool_scan = cached_scan(rest, course_id)
    _skipped_tools = 0

    def _emit(kind, **kw):
        if on_event is None:
            return
        try:
            on_event(kind, **kw)
        except Exception:
            pass

    def add(vid, title, *, module="", launch="", source="module", item_id=0):
        vid = (vid or "").lower()
        if vid and vid not in videos:
            videos[vid] = PanoptoVideo(
                video_id=vid, title=title, module_name=module,
                launch_url=launch, source=source, module_item_id=item_id,
            )
            _emit('video', title=title, source=source)

    def _cancelled() -> bool:
        return bool(is_cancelled and is_cancelled())

    # ── Modules ──
    _emit('stage', name='Modules')
    modules = rest.get_all(
        f"/api/v1/courses/{course_id}/modules", {"include[]": "items", "per_page": 50}
    )

    # Pass 1 (cheap, sequential): direct GUID extraction from the module items
    # already in hand. EVERY ExternalTool item is queued for a per-item LTI
    # launch in pass 2 - even one that embeds a GUID: after an LTI 1.3
    # migration the embedded ``custom_context_delivery`` ids can be stale
    # (Panopto re-homed the sessions) while the launch always resolves the
    # CURRENT session (2026-07-09 CBS: all 6 embedded ids were dead, and the
    # other 30 bare LTI.aspx links carried no id anywhere in their JSON). The
    # direct ids ride along in the queue entry as a fallback for when the
    # launch fails.
    pending: list[tuple] = []
    for mod in modules:
        if _cancelled():
            return list(videos.values())
        mod_name = mod.get("name", "") or ""
        if mod_name:
            _emit('scan', detail=f"Module: {mod_name}")
        for item in mod.get("items", []):
            item_title = item.get("title", "Untitled")
            item_id = int(item.get("id", 0) or 0)
            if item.get("type") in (
                "File", "Page", "Assignment", "Discussion", "Quiz", "SubHeader"
            ):
                continue

            launch_url = item.get("url", "") or ""
            direct_vids: list[str] = []
            for field_name in ("external_url", "url", "html_url"):
                for vid in extract_panopto_ids(item.get(field_name) or ""):
                    if vid not in direct_vids:
                        direct_vids.append(vid)

            # quiz_lti marks Canvas New Quizzes - an LTI tool, never Panopto;
            # launching it would waste a full handshake per quiz.
            if item.get("type") == "ExternalTool" and not item.get("quiz_lti"):
                # Same idea, generalised: an item whose tool we can POSITIVELY
                # identify as some other vendor's cannot yield a recording, and
                # pass 2 costs ~1-2s of LTI handshake for each one. Measured on
                # a real account: course 45899 had 12 ExternalTool items, every
                # one of them the ExLibris library tool - 12 full handshakes
                # that could only ever return nothing. The Panopto course next
                # to it had 36, all Panopto, all genuinely needed.
                #
                # SKIP ONLY WHAT WE CAN PROVE IS NOT PANOPTO. An unknown tool id
                # (or none) still gets its handshake, so a course-level Panopto
                # install we never listed can never be lost. Tool ids are
                # resolved per institution at runtime and are never hardcoded -
                # Panopto is 863 on one Canvas and something else on the next.
                if not direct_vids and _tool_scan.is_known_non_panopto_tool(
                        item.get("content_id")):
                    _skipped_tools += 1
                    continue
                pending.append((mod, item, mod_name, item_title, item_id,
                                launch_url, direct_vids))
            else:
                for vid in direct_vids:
                    add(vid, item_title, module=mod_name, launch=launch_url,
                        source="module", item_id=item_id)

    if _skipped_tools:
        logger.info(
            "Panopto discovery: skipped %d non-Panopto ExternalTool item(s) in "
            "course %s (~%.0f-%.0fs of LTI handshakes avoided); %d to resolve.",
            _skipped_tools, course_id, _skipped_tools, _skipped_tools * 2,
            len(pending),
        )

    # Pass 2 (parallel): the slow part. Each pending ExternalTool item needs an
    # LTI handshake (and possibly an item-detail fetch) - ~1-2s of pure network
    # I/O each. They are independent (own request/session, read-only token), so
    # Finding them concurrently turns N×2s of sequential waiting into a handful
    # of round-trips. add()/folder-expansion stay sequential in pass 3.
    def _resolve(entry):
        mod, item, mod_name, item_title, item_id, launch_url, direct_vids = entry
        direct: list[str] = list(direct_vids)
        d_launch = launch_url
        lti = None
        used_launch = ""

        # The MODULE-ITEM launch replicates a browser click on THIS item:
        # Canvas builds the LTI 1.3 request from the item's own resource link,
        # so Panopto lands on the recording's Viewer/Embed page (session id in
        # the URL). The item's own ``url`` field is only
        # ``sessionless_launch?id=<tool>&url=LTI.aspx`` - a GENERIC tool launch
        # with no per-item context - which lands on the course FOLDER page
        # instead (the 2026-07-09 CBS failure: 30/36 links unresolvable).
        mi_launch = ""
        if item_id:
            mi_launch = (
                f"{canvas_base.rstrip('/')}/api/v1/courses/{course_id}"
                f"/external_tools/sessionless_launch"
                f"?launch_type=module_item&module_item_id={item_id}"
            )
            if item.get("content_id"):
                mi_launch += f"&id={item['content_id']}"
            try:
                # (session, final_url, real_id, pbase, folder_id)
                attempt = lti_launch(mi_launch, token)
            except Exception:
                attempt = None
            if attempt and attempt[0] is not None and attempt[3] is not None:
                lti, used_launch = attempt, mi_launch

        if lti is None or (not lti[2] and not direct):
            # Legacy fallback: item detail + the item's own launch URL (the
            # pre-1.3 route; its folder landing also feeds the title matcher).
            try:
                detail = rest.get_one(
                    f"/api/v1/courses/{course_id}/modules/{mod['id']}/items/{item['id']}"
                )
            except Exception:
                detail = {}
            d_launch = detail.get("url", launch_url) or launch_url
            for field_name in ("external_url", "url", "html_url"):
                for vid in extract_panopto_ids(detail.get(field_name) or ""):
                    if vid not in direct:
                        direct.append(vid)
            if (lti is None and not direct and d_launch
                    and "sessionless_launch" in d_launch and d_launch != mi_launch):
                try:
                    attempt = lti_launch(d_launch, token)
                except Exception:
                    attempt = None
                if attempt and attempt[0] is not None:
                    lti, used_launch = attempt, d_launch
        return entry, d_launch, direct, lti, used_launch

    resolved: list[tuple] = []
    if pending and not _cancelled():
        import concurrent.futures as _cf
        _emit('scan', detail=f"Finding {len(pending)} lecture link(s)…")
        try:
            with _cf.ThreadPoolExecutor(max_workers=min(6, len(pending))) as _ex:
                resolved = list(_ex.map(_resolve, pending))
        except Exception as e:
            logger.debug(f"Parallel LTI resolution failed, falling back: {e}")
            resolved = [_resolve(e) for e in pending]

    # Pass 3 (sequential): apply the resolved results - add() and folder-session
    # expansion. add() is idempotent, so the final de-duplicated set matches the
    # original sequential flow exactly.
    #
    # Folder-landing fallback: some Panopto LTI configurations resolve EVERY
    # per-item launch to the course folder's Sessions/List.aspx (authenticated,
    # but no session id in URL or body - the list is loaded client-side). The
    # 2026-07-09 CBS course showed 30/36 links landing there. In that case the
    # launch DID hand us the folder id, so enumerate the folder's sessions ONCE
    # via the Panopto API and resolve each item by recording title.
    _folder_sessions_cache: dict[tuple[str, str], list] = {}
    _unmatched_titles: list[str] = []
    _auth_beacon = ""   # first launch VERIFIED to reach a Panopto host this run
    # Folder-scope body sniff (include_folder_sessions): a VIEWER landing only
    # reveals its home folder inside the page body, which costs one page GET.
    # Every module item of a course shares that home folder, so sniff it once
    # per course instead of once per item (36 sequential GETs on the CBS run).
    _viewer_folder_sniffed = False
    for entry, d_launch, direct, lti, used_launch in resolved:
        if _cancelled():
            break
        mod, item, mod_name, item_title, item_id, launch_url, _p1_vids = entry
        # The stored launch is the one that actually REACHED Panopto this run
        # (the runner re-uses it for the per-video DeliveryInfo auth fallback).
        item_launch = used_launch or d_launch
        _before = len(videos)
        real_id = lti[2] if lti is not None else None
        if real_id:
            # Launch-resolved id is authoritative: it is what a browser click
            # on this item plays TODAY. Any GUID embedded in the item JSON that
            # disagrees is a leftover from before an LTI migration - adding it
            # would download dead/wrong content, so it is dropped (logged).
            add(real_id, item_title, module=mod_name, launch=item_launch,
                source="module", item_id=item_id)
            _stale = [d for d in direct if d != real_id]
            if _stale:
                logger.info(
                    "Panopto: module link '%s' launch-resolves to %s - ignoring "
                    "embedded stale id(s): %s",
                    item_title, real_id, ", ".join(_stale),
                )
        else:
            for vid in direct:
                add(vid, item_title, module=mod_name, launch=item_launch,
                    source="module", item_id=item_id)
        if lti is not None:
            session, final_url, _rid, pbase, lti_folder = lti
            if pbase and session and item_launch and not _auth_beacon:
                _auth_beacon = item_launch
            for vid in extract_panopto_ids(final_url or ""):
                add(vid, item_title, module=mod_name, launch=item_launch,
                    source="module", item_id=item_id)

            if len(videos) == _before and session and pbase and lti_folder:
                _fkey = (pbase, lti_folder)
                if _fkey not in _folder_sessions_cache:
                    _folder_sessions_cache[_fkey] = _discover_folder_sessions(
                        session, pbase, lti_folder
                    )
                    logger.info(
                        "Panopto folder-landing fallback: enumerated %d "
                        "session(s) in folder %s for title matching",
                        len(_folder_sessions_cache[_fkey]), lti_folder,
                    )
                _match = _match_session_by_title(
                    item_title, _folder_sessions_cache[_fkey], videos
                )
                if _match:
                    add(_match, item_title, module=mod_name, launch=item_launch,
                        source="module", item_id=item_id)
                else:
                    _unmatched_titles.append(item_title)

            if include_folder_sessions and session and final_url and pbase:
                folder_id = lti_folder
                if not folder_id:
                    folder_m = PANOPTO_FOLDER_PATTERN.search(final_url)
                    if not folder_m and (not real_id or not _viewer_folder_sniffed):
                        try:
                            page_r = session.get(final_url, timeout=15)
                            folder_m = PANOPTO_FOLDER_PATTERN.search(page_r.text)
                        except Exception:
                            pass
                        if real_id:
                            _viewer_folder_sniffed = True
                    folder_id = folder_m.group(1) if folder_m else None
                if folder_id:
                    _fkey = (pbase, folder_id.lower())
                    if _fkey not in _folder_sessions_cache:
                        _folder_sessions_cache[_fkey] = _discover_folder_sessions(
                            session, pbase, _fkey[1]
                        )
                    for vid, vtitle in _folder_sessions_cache[_fkey]:
                        add(vid, vtitle, module=mod_name, launch=item_launch,
                            source="folder", item_id=item_id)

    if _unmatched_titles:
        logger.info(
            "Panopto folder-landing fallback could not match %d link(s) by "
            "title: %s",
            len(_unmatched_titles), "; ".join(_unmatched_titles[:10]),
        )
        # Log BOTH sides of the failed match: without the folder's actual
        # session names the mismatch cannot be diagnosed from the log.
        for _fkey, _sessions in _folder_sessions_cache.items():
            logger.info(
                "Panopto folder %s holds %d session(s): %s",
                _fkey[1], len(_sessions),
                "; ".join(name for _vid, name in _sessions[:12]),
            )

    # Heal stale direct ids: a module item can embed a delivery GUID that no
    # longer exists after a Panopto migration (the June-era CBS links carry
    # ids the platform has since re-homed - DeliveryInfo answers "This session
    # isn't available. It may have been deleted." for every one of them, on
    # every platform). When the course folder WAS enumerated this run, any
    # module-linked id absent from the folder is re-resolved by title against
    # the folder's sessions: a match adopts the live id (logged); no match
    # leaves the video untouched (it may legitimately live outside this
    # folder, and a dead id fails loudly rather than downloading silently
    # wrong content).
    _all_folder_sessions = [s for _lst in _folder_sessions_cache.values() for s in _lst]
    if _all_folder_sessions:
        _live_ids = {vid for vid, _name in _all_folder_sessions}
        for _old_id in list(videos):
            _v = videos[_old_id]
            if _v.source != "module" or _old_id in _live_ids:
                continue
            _new_id = _match_session_by_title(_v.title, _all_folder_sessions, videos)
            if _new_id:
                logger.info(
                    "Panopto: module link '%s' carries a stale delivery id "
                    "(%s not in the course folder) - remapped to %s by title.",
                    _v.title, _old_id, _new_id,
                )
                _v.video_id = _new_id
                videos[_new_id] = videos.pop(_old_id)

    # Hand the runner a VERIFIED auth launch: legacy items can carry launch
    # URLs whose own LTI chain no longer completes (they die on the Canvas
    # tool page), which left the session bootstrap with nothing that works
    # even though discovery just authenticated 30 times. Every video gets the
    # beacon; the bootstrap tries it before the per-item URLs.
    if _auth_beacon:
        for v in videos.values():
            if not v.auth_launch_url:
                v.auth_launch_url = _auth_beacon

    # ── Pages ──
    if not _cancelled():
        _emit('stage', name='Pages')
        for stub in rest.get_all(f"/api/v1/courses/{course_id}/pages"):
            if _cancelled():
                break
            _title = stub.get("title", "") or stub.get("url", "")
            if _title:
                _emit('scan', detail=f"Page: {_title}")
            page = rest.get_one(f"/api/v1/courses/{course_id}/pages/{stub.get('url', '')}")
            for vid in extract_panopto_ids(page.get("body") or ""):
                add(vid, page.get("title", "Page"), source="page")

    # ── Assignments ──
    if not _cancelled():
        _emit('stage', name='Assignments')
        for a in rest.get_all(f"/api/v1/courses/{course_id}/assignments"):
            for vid in extract_panopto_ids(a.get("description") or ""):
                add(vid, a.get("name", "Assignment"), source="assignment")

    # ── Announcements ──
    if not _cancelled():
        _emit('stage', name='Announcements')
        for ann in rest.get_all(
            f"/api/v1/courses/{course_id}/discussion_topics",
            {"only_announcements": "true"},
        ):
            for vid in extract_panopto_ids(ann.get("message") or ""):
                add(vid, ann.get("title", "Announcement"), source="announcement")

    return list(videos.values())
