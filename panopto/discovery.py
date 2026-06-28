"""Discover Panopto recordings linked in a Canvas course.

Scans modules, pages, assignments and announcements via the Canvas REST API
(reusing the logged-in token + resolved base URL) and extracts Panopto video
GUIDs. ExternalTool launch links are resolved through the LTI handshake.

Parametrized by Canvas base + token (no hardcoded institution). Returns a list
of ``PanoptoVideo`` records, de-duplicated by video id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

from panopto.auth import (
    PANOPTO_FOLDER_PATTERN, extract_panopto_ids, lti_launch,
)

logger = logging.getLogger(__name__)


@dataclass
class PanoptoVideo:
    video_id: str                 # Panopto GUID (lowercased)
    title: str                    # human-readable recording title
    module_name: str = ""         # sanitized-later module name, "" if not module-linked
    launch_url: str = ""          # Canvas sessionless_launch API url (for auth)
    source: str = "module"        # module | page | assignment | announcement | folder
    module_item_id: int = 0       # Canvas module item id (for stable manifest ids)


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
    try:
        r = session.get(
            f"{panopto_base}/Panopto/api/v1/{path}",
            params=params or {},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _discover_folder_sessions(session, panopto_base, folder_id) -> list[tuple[str, str]]:
    found, page = [], 0
    while True:
        data = _panopto_api_get(
            session, panopto_base, f"folders/{folder_id}/sessions",
            {"pageNumber": page, "pageSize": 100, "sortField": "1", "sortOrder": "0"},
        )
        if data is None:
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
                lti = lti_launch(d_launch, token)  # (session, final_url, real_id, pbase)
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
    for entry, d_launch, direct, lti in resolved:
        if _cancelled():
            break
        mod, item, mod_name, item_title, item_id, launch_url = entry
        for vid in direct:
            add(vid, item_title, module=mod_name, launch=d_launch,
                source="module", item_id=item_id)
        if lti is not None:
            session, final_url, real_id, pbase = lti
            if real_id:
                add(real_id, item_title, module=mod_name, launch=d_launch,
                    source="module", item_id=item_id)
            for vid in extract_panopto_ids(final_url or ""):
                add(vid, item_title, module=mod_name, launch=d_launch,
                    source="module", item_id=item_id)

            if include_folder_sessions and session and final_url and pbase:
                folder_m = PANOPTO_FOLDER_PATTERN.search(final_url)
                if not folder_m:
                    try:
                        page_r = session.get(final_url, timeout=15)
                        folder_m = PANOPTO_FOLDER_PATTERN.search(page_r.text)
                    except Exception:
                        pass
                if folder_m:
                    for vid, vtitle in _discover_folder_sessions(
                        session, pbase, folder_m.group(1)
                    ):
                        add(vid, vtitle, module=mod_name, launch=d_launch,
                            source="folder", item_id=item_id)

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
