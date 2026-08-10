"""Oracle O5 - what SHOULD exist, enumerated independently of the application.

This is the only view in the suite that the app does not produce, and it is the
reason the suite can catch a discovery bug at all. The UI, the debug log and the
folder contents are all downstream of ``_get_files_from_modules``: if it misses
thirty files, all three agree on the wrong number and every one of them looks
green.

It is deliberately NOT a reimplementation of the app's discovery. Reproducing
the app's logic would reproduce its bugs and the two would agree by
construction. Instead this asks Canvas the plainest possible questions - what
files does this course expose, what do its modules contain, which entities
exist - and leaves the interpretation to the crosscheck layer, which is allowed
to know that (for instance) a teacher-locked file has no URL and is therefore
legitimately absent from disk.

The hybrid-fetch problem is why both sources are enumerated. In these courses
the Files tab is frequently restricted while the modules still expose the same
files, and the app compensates by taking the union - so O5 takes the union too,
and reports each side separately so a check can tell WHICH source a missing
file should have come from.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

INLINE_FILE_LINK = re.compile(r"/files/(\d+)")


def inline_linked_file_ids(html: str) -> set[int]:
    r"""File ids an instructor LINKED in a body, mirroring the product exactly.

    ``core.canvas_logic._extract_canvas_file_links`` reads ``<a href>`` and
    nothing else, and that is a deliberate contract: an ``<img src>`` in a
    discussion body is a decorative banner rendered inside the saved HTML, not
    an attachment the student is missing.

    A raw ``/files/(\d+)`` sweep of the HTML does not respect that. Measured on
    course 43658, whose two discussion bodies open with the same 15 KB banner
    image: it matched the ``<img src>`` AND the ``data-api-endpoint`` attribute
    beside it, so the discovery check demanded a file the app is not supposed
    to fetch and filed "1 file(s) exist on Canvas but were never tracked" at
    severity **high**. An oracle that is stricter than the product does not
    find bugs, it invents them.

    Falls back to the regex only when bs4 is unavailable - the same fallback
    shape the product has, and noisy in the same direction.
    """
    if not html:
        return set()
    try:
        from bs4 import BeautifulSoup
    except Exception:                       # pragma: no cover - bs4 is a dep
        return {int(x) for x in INLINE_FILE_LINK.findall(html)}
    out: set[int] = set()
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = a["href"]
        if "/files/" not in href:
            continue
        try:
            out.add(int(href.split("/files/", 1)[1].split("/")[0].split("?")[0]))
        except (IndexError, ValueError):
            continue
    return out


def _audit_token(url: str) -> tuple[str | None, str]:
    """The AUDIT's own Canvas credential. Returns (token, where_it_came_from).

    The OS keyring is tried first and is the right default: it is where the
    product keeps the token, so using it keeps the audit honest about the
    machine actually being signed in.

    It is not, however, always reachable - and the failure is macOS-specific and
    total. The Keychain is scoped to the launchd SECURITY session, so a harness
    driven from an SSH tmux (`Background`) gets errSecInteractionNotAllowed
    (-25308) for every operation, including creating a brand-new item of its
    own. Measured 2026-08-10: the same shell wrote a 4.4 MB `screencapture` PNG
    and got answers from System Events, so nothing else in the audit gave any
    hint - O5 simply died with a keyring traceback before the first row ran.
    See `scripts/mac_aqua.py`, and note the doctor now BLOCKs on it.

    A second problem lands in the same place: an item written by
    `/usr/bin/security` (which is how `scripts/mac_audit_bootstrap.sh` used to
    seed it) carries an ACL naming only that binary, so python is asked to
    authorise itself and authorising an ACL change needs the *login keychain's*
    password - frequently unknown on a cloud image.

    So the fallbacks exist to stop an environment problem masquerading as a
    product finding. This is the audit's identity, not the application's:
    O5's whole purpose is to enumerate Canvas from OUTSIDE the app, so where its
    own credential comes from cannot weaken a finding. Nothing here changes what
    the PRODUCT does with the Keychain, which phase M5 still tests directly.
    """
    import os

    try:
        import keyring
        tok = keyring.get_password("CanvasDownloader", url)
        if tok:
            return tok, "keyring"
    except Exception as e:                                  # noqa: BLE001
        _kr_note = f"{type(e).__name__}: {e}"[:160]
    else:
        _kr_note = "keyring held no token for this url"

    for var in ("CANVAS_DL_AUDIT_TOKEN", "CANVAS_TOKEN"):
        if os.environ.get(var):
            return os.environ[var], f"${var}"

    # The place `tests/audit/MAC_AUDIT_GUIDE.md` already tells the operator to
    # put it, so a Mac session needs no extra ceremony per command.
    secrets = Path(os.path.expanduser("~/mac_audit_secrets.env"))
    if secrets.is_file():
        try:
            for line in secrets.read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                if k.strip() in ("CANVAS_TOKEN", "CANVAS_DL_AUDIT_TOKEN") and v.strip():
                    return v.strip().strip('"').strip("'"), str(secrets)
        except OSError:
            pass
    return None, _kr_note


def _client():
    """Canvas client built from the DEVELOPER's real credentials.

    Note this reads the real config, not the audit's isolated copy: the audit
    isolates application STATE, not the identity it runs as - the whole point is
    to exercise the same account against the same courses the user has.
    """
    import json as _json
    from canvasapi import Canvas

    from ..paths import REPO_ROOT
    cfg_path = REPO_ROOT / "canvas_downloader_settings.json"
    cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    url = cfg["api_url"]
    token, source = _audit_token(url)
    if not token:
        raise SystemExit(
            f"No Canvas token available for {url} ({source}). Sign in once in "
            "the real app, or export CANVAS_DL_AUDIT_TOKEN. On macOS check "
            "`python3 scripts/mac_aqua.py check` first - a Background launchd "
            "session cannot read the Keychain at all.")
    return Canvas(url, token), url


def _safe(fn, default=None, note: dict | None = None, label: str = ""):
    """Call an endpoint that may legitimately be forbidden for a student.

    Failures are RECORDED, never swallowed: an endpoint that starts returning
    403 changes what the app can possibly download, and an audit that silently
    treated that as "nothing there" would report a discovery regression as a
    clean run.
    """
    try:
        return fn()
    except Exception as e:
        if note is not None:
            note[label or fn.__name__] = f"{type(e).__name__}: {e}"[:300]
        return default


def enumerate_course(course_id: int, deep: bool = True) -> dict:
    started = time.time()
    canvas, api_url = _client()
    notes: dict = {}

    course = canvas.get_course(course_id)
    out: dict = {
        "course_id": course_id,
        "api_url": api_url,
        "name": getattr(course, "name", ""),
        "course_code": getattr(course, "course_code", ""),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # -- folders (needed to turn a file's folder_id into a path) ----------
    folders = {}
    for f in _safe(lambda: list(course.get_folders()), [], notes, "folders") or []:
        folders[getattr(f, "id", 0)] = {
            "id": getattr(f, "id", 0),
            "full_name": getattr(f, "full_name", ""),
            "name": getattr(f, "name", ""),
            "hidden": bool(getattr(f, "hidden", False)),
            "locked": bool(getattr(f, "locked", False)),
        }
    out["folders"] = folders

    # -- the Files tab ----------------------------------------------------
    files_tab = {}
    for f in _safe(lambda: list(course.get_files()), [], notes, "files_tab") or []:
        fid = getattr(f, "id", 0)
        files_tab[fid] = {
            "id": fid,
            "filename": getattr(f, "filename", ""),
            "display_name": getattr(f, "display_name", ""),
            "size": int(getattr(f, "size", 0) or 0),
            "content_type": getattr(f, "content-type", None) or
                            getattr(f, "content_type", ""),
            "updated_at": getattr(f, "updated_at", ""),
            "folder_id": getattr(f, "folder_id", None),
            "md5": getattr(f, "md5", None),
            "hidden": bool(getattr(f, "hidden", False)),
            "locked": bool(getattr(f, "locked", False)),
            "locked_for_user": bool(getattr(f, "locked_for_user", False)),
            # A file object with no url is teacher-locked. The app reports these
            # as a permanent 'Locked File' rather than a failure, so the audit
            # must not count them as missing downloads.
            "has_url": bool(getattr(f, "url", "")),
            "folder_path": folders.get(getattr(f, "folder_id", None), {}).get("full_name", ""),
        }
    out["files_tab"] = files_tab

    # -- modules and their items ------------------------------------------
    modules, module_file_ids, item_types = [], set(), {}
    for m in _safe(lambda: list(course.get_modules()), [], notes, "modules") or []:
        items = _safe(lambda m=m: list(m.get_module_items()), [], notes,
                      f"module_items:{getattr(m, 'id', '?')}") or []
        recs = []
        for it in items:
            t = getattr(it, "type", "")
            item_types[t] = item_types.get(t, 0) + 1
            rec = {
                "id": getattr(it, "id", 0),
                "type": t,
                "title": getattr(it, "title", ""),
                "content_id": getattr(it, "content_id", None),
                "page_url": getattr(it, "page_url", None),
                "external_url": getattr(it, "external_url", None),
                "published": getattr(it, "published", None),
            }
            if t == "File" and rec["content_id"]:
                module_file_ids.add(int(rec["content_id"]))
            recs.append(rec)
        modules.append({"id": getattr(m, "id", 0), "name": getattr(m, "name", ""),
                        "position": getattr(m, "position", 0),
                        "published": getattr(m, "published", None),
                        "item_count": len(recs), "items": recs})
    out["modules"] = modules
    out["module_item_types"] = item_types
    out["module_file_ids"] = sorted(module_file_ids)

    out["only_in_modules"] = sorted(module_file_ids - set(files_tab))
    out["only_in_files_tab"] = sorted(set(files_tab) - module_file_ids)
    out["files_tab_restricted"] = bool(notes.get("files_tab")) or (
        len(files_tab) == 0 and bool(module_file_ids))

    if not deep:
        out["expected_file_ids"] = sorted(set(files_tab) | module_file_ids)
        out["notes"] = notes
        out["elapsed_s"] = round(time.time() - started, 1)
        return out

    # -- secondary entities ------------------------------------------------
    # Every one of these becomes a NEGATIVE-id synthetic entity in the app's
    # manifest, so their counts are directly comparable against O4's by_entity.
    inline_ids: set[int] = set()

    def _bodies(objs, *attrs):
        for o in objs:
            for a in attrs:
                yield getattr(o, a, "") or ""

    assignments = _safe(lambda: list(course.get_assignments()), [], notes, "assignments") or []
    out["assignments"] = [{
        "id": getattr(a, "id", 0), "name": getattr(a, "name", ""),
        "due_at": getattr(a, "due_at", None),
        "points": getattr(a, "points_possible", None),
        "has_rubric": bool(getattr(a, "rubric", None)),
        "submission_types": getattr(a, "submission_types", []),
    } for a in assignments]

    quizzes = _safe(lambda: list(course.get_quizzes()), [], notes, "quizzes") or []
    out["quizzes"] = [{"id": getattr(q, "id", 0), "title": getattr(q, "title", "")}
                      for q in quizzes]

    discussions = _safe(lambda: list(course.get_discussion_topics()), [],
                        notes, "discussions") or []
    anns = _safe(lambda: list(course.get_discussion_topics(only_announcements=True)),
                 [], notes, "announcements") or []
    ann_ids = {getattr(a, "id", 0) for a in anns}
    out["announcements"] = [{"id": getattr(a, "id", 0), "title": getattr(a, "title", ""),
                             "posted_at": getattr(a, "posted_at", None)} for a in anns]
    out["discussions"] = [{"id": getattr(d, "id", 0), "title": getattr(d, "title", "")}
                          for d in discussions if getattr(d, "id", 0) not in ann_ids]

    pages = _safe(lambda: list(course.get_pages()), [], notes, "pages") or []
    out["pages"] = [{"url": getattr(p, "url", ""), "title": getattr(p, "title", "")}
                    for p in pages]
    out["pages_restricted"] = bool(notes.get("pages"))

    syl = _safe(lambda: canvas.get_course(course_id, include=["syllabus_body"]),
                None, notes, "syllabus")
    body = getattr(syl, "syllabus_body", "") if syl else ""
    out["syllabus_present"] = bool(body and body.strip())

    # Inline ``/files/<id>`` links inside every HTML body the app parses. These
    # are the "meta" files the product downloads from Canvas Content, and they
    # are the population most likely to be mishandled by sync, so they are
    # enumerated explicitly rather than inferred.
    # Recorded PER SOURCE, not as one pool. A body the run did not ask for is
    # never fetched, so its inline links are never followed - and folding them
    # all together made the discovery check demand files from Canvas Content
    # types the run had switched OFF. Measured on course 43658 with only
    # discussions and quizzes enabled: one announcement attachment reported as
    # "exists on Canvas but was never tracked", severity high. Most rows of a
    # covering array enable only some types, so that was a false HIGH on most
    # of the matrix.
    by_source: dict[str, set] = {}
    embedded: set = set()

    def _collect(kind, texts):
        got = by_source.setdefault(kind, set())
        for text in texts:
            got |= inline_linked_file_ids(text or "")
            # Everything the raw sweep sees that an anchor does not: <img>
            # banners, data-api-endpoint attributes, preview iframes. Recorded
            # separately so the difference between "the app skipped it" and
            # "the app was never meant to fetch it" stays visible.
            embedded.update(int(x) for x in INLINE_FILE_LINK.findall(text or ""))

    _collect("assignment", _bodies(assignments, "description"))
    _collect("discussion", _bodies(discussions, "message"))
    _collect("announcement", _bodies(anns, "message"))
    _collect("syllabus", [body] if body else [])
    for k, v in by_source.items():
        inline_ids.update(v)
    out["inline_by_source"] = {k: sorted(v) for k, v in sorted(by_source.items())}
    out["inline_file_ids"] = sorted(inline_ids)
    out["embedded_only_file_ids"] = sorted(embedded - inline_ids)
    # Files reachable ONLY by following a link inside an HTML body - not in the
    # Files tab, not attached to a module. They are the population most likely
    # to be lost: nothing enumerates them, so they exist only if the app parses
    # every body it downloads. On course 45899 (Files tab 403) this is where the
    # assignment attachments live.
    out["inline_only_file_ids"] = sorted(inline_ids - set(files_tab) - module_file_ids)

    # The full union the app is expected to end up with.
    out["expected_file_ids"] = sorted(set(files_tab) | module_file_ids | inline_ids)

    out["secondary_counts"] = {
        "assignment": len(out["assignments"]),
        "quiz": len(out["quizzes"]),
        "discussion": len(out["discussions"]),
        "announcement": len(out["announcements"]),
        "page": len(out["pages"]),
        "syllabus": 1 if out["syllabus_present"] else 0,
    }
    out["notes"] = notes
    out["elapsed_s"] = round(time.time() - started, 1)
    return out


def snapshot(course_id: int, cache_dir: str | Path, refresh: bool = False,
             deep: bool = True) -> dict:
    """Enumerate once per run and cache. Courses are static during an audit."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"course_{course_id}.json"
    if p.is_file() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    data = enumerate_course(course_id, deep=deep)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def brief(snap: dict) -> dict:
    """Counts only - the full snapshot is far too large for a transcript."""
    ft = snap.get("files_tab", {})
    downloadable = [f for f in ft.values() if f["has_url"]]
    return {
        "course_id": snap.get("course_id"),
        "name": snap.get("name"),
        "course_code": snap.get("course_code"),
        "files_tab": len(ft),
        "files_tab_downloadable": len(downloadable),
        "files_tab_locked": len(ft) - len(downloadable),
        "files_tab_bytes": sum(f["size"] for f in downloadable),
        "module_files": len(snap.get("module_file_ids", [])),
        "expected_file_ids": len(snap.get("expected_file_ids", [])),
        "only_in_modules": len(snap.get("only_in_modules", [])),
        "only_in_files_tab": len(snap.get("only_in_files_tab", [])),
        "files_tab_restricted": snap.get("files_tab_restricted"),
        "modules": len(snap.get("modules", [])),
        "module_item_types": snap.get("module_item_types", {}),
        "secondary_counts": snap.get("secondary_counts", {}),
        "inline_file_ids": len(snap.get("inline_file_ids", [])),
        "inline_only_file_ids": len(snap.get("inline_only_file_ids", [])),
        "pages_restricted": snap.get("pages_restricted"),
        "notes": snap.get("notes", {}),
        "elapsed_s": snap.get("elapsed_s"),
    }


def list_courses() -> list[dict]:
    canvas, _ = _client()
    user = canvas.get_current_user()
    rows = []
    for c in user.get_courses(enrollment_state="active"):
        rows.append({"id": getattr(c, "id", 0),
                     "code": getattr(c, "course_code", ""),
                     "name": getattr(c, "name", "")})
    return sorted(rows, key=lambda r: r["code"])
