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


def _folder_sessions_data_svc(session, panopto_base, folder_id) -> list[tuple[str, str]]:
    """Enumerate a folder via the INTERNAL ``Data.svc/GetSessions`` endpoint.

    This is the exact call ``Sessions/List.aspx`` itself makes to render the
    session list, so it works with the plain page cookies wherever the list
    page renders - including tenants whose ``api/v1`` rejects cookie auth
    (CBS: api/v1 yielded nothing while the list page showed all recordings).
    Results carry ``DeliveryID`` (the id DeliveryInfo wants) + ``SessionName``.
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
        try:
            r = session.post(
                f"{panopto_base}/Panopto/Services/Data.svc/GetSessions",
                json=payload,
                headers={"Accept": "application/json"},
                timeout=30,
            )
        except Exception as e:
            logger.info("Panopto GetSessions failed for folder %s: %s", folder_id, e)
            break
        if r.status_code != 200:
            logger.info(
                "Panopto GetSessions returned HTTP %s for folder %s "
                "(body starts: %.120s)",
                r.status_code, folder_id, (r.text or "").strip(),
            )
            break
        try:
            data = (r.json() or {}).get("d") or {}
        except Exception as e:
            logger.info("Panopto GetSessions returned non-JSON for folder %s: %s",
                        folder_id, e)
            break
        results = data.get("Results") or []
        for item in results:
            vid = (item.get("DeliveryID") or item.get("SessionID")
                   or item.get("Id") or "").lower()
            name = (item.get("SessionName") or item.get("Name") or "Unnamed")
            if vid:
                found.append((vid, name))
        total = data.get("TotalNumber")
        if page == 0:
            logger.info(
                "Panopto GetSessions: folder %s reports %s session(s) "
                "(page 0 returned %d).",
                folder_id, total if total is not None else "?", len(results),
            )
        if len(results) < 100:
            break
        if isinstance(total, int) and len(found) >= total:
            break
        page += 1
    return found


def _discover_folder_sessions(session, panopto_base, folder_id) -> list[tuple[str, str]]:
    """All ``(delivery_id, name)`` sessions in *folder_id* - api/v1 first,
    then the Data.svc/GetSessions fallback the list page itself uses."""
    found = _folder_sessions_api_v1(session, panopto_base, folder_id)
    if not found:
        found = _folder_sessions_data_svc(session, panopto_base, folder_id)
    return found


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
    # already in hand, and queue ExternalTool items that still need a network
    # round-trip (item detail fetch + LTI handshake) to resolve their GUID.
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

            before = len(videos)
            launch_url = item.get("url", "") or ""

            for field_name in ("external_url", "url", "html_url"):
                for vid in extract_panopto_ids(item.get(field_name) or ""):
                    add(vid, item_title, module=mod_name, launch=launch_url,
                        source="module", item_id=item_id)

            if item.get("type") == "ExternalTool" and len(videos) == before:
                pending.append((mod, item, mod_name, item_title, item_id, launch_url))

    # Pass 2 (parallel): the slow part. Each pending ExternalTool item needs an
    # item-detail fetch and (usually) an LTI handshake - ~1-2s of pure network
    # I/O each. They are independent (own request/session, read-only token), so
    # Finding them concurrently turns N×2s of sequential waiting into a handful
    # of round-trips. add()/folder-expansion stay sequential in pass 3.
    def _resolve(entry):
        mod, item, mod_name, item_title, item_id, launch_url = entry
        try:
            detail = rest.get_one(
                f"/api/v1/courses/{course_id}/modules/{mod['id']}/items/{item['id']}"
            )
        except Exception:
            detail = {}
        d_launch = detail.get("url", launch_url) or launch_url
        direct: list[str] = []
        for field_name in ("external_url", "url", "html_url"):
            direct.extend(extract_panopto_ids(detail.get(field_name) or ""))
        lti = None
        if not direct and d_launch and "sessionless_launch" in d_launch:
            try:
                # (session, final_url, real_id, pbase, folder_id)
                lti = lti_launch(d_launch, token)
            except Exception:
                lti = None
        return entry, d_launch, direct, lti

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
    for entry, d_launch, direct, lti in resolved:
        if _cancelled():
            break
        mod, item, mod_name, item_title, item_id, launch_url = entry
        _before = len(videos)
        for vid in direct:
            add(vid, item_title, module=mod_name, launch=d_launch,
                source="module", item_id=item_id)
        if lti is not None:
            session, final_url, real_id, pbase, lti_folder = lti
            if pbase and session and d_launch and not _auth_beacon:
                _auth_beacon = d_launch
            if real_id:
                add(real_id, item_title, module=mod_name, launch=d_launch,
                    source="module", item_id=item_id)
            for vid in extract_panopto_ids(final_url or ""):
                add(vid, item_title, module=mod_name, launch=d_launch,
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
                    add(_match, item_title, module=mod_name, launch=d_launch,
                        source="module", item_id=item_id)
                else:
                    _unmatched_titles.append(item_title)

            if include_folder_sessions and session and final_url and pbase:
                folder_id = lti_folder
                if not folder_id:
                    folder_m = PANOPTO_FOLDER_PATTERN.search(final_url)
                    if not folder_m:
                        try:
                            page_r = session.get(final_url, timeout=15)
                            folder_m = PANOPTO_FOLDER_PATTERN.search(page_r.text)
                        except Exception:
                            pass
                    folder_id = folder_m.group(1) if folder_m else None
                if folder_id:
                    _fkey = (pbase, folder_id.lower())
                    if _fkey not in _folder_sessions_cache:
                        _folder_sessions_cache[_fkey] = _discover_folder_sessions(
                            session, pbase, _fkey[1]
                        )
                    for vid, vtitle in _folder_sessions_cache[_fkey]:
                        add(vid, vtitle, module=mod_name, launch=d_launch,
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
