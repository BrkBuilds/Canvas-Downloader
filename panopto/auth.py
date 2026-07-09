"""Canvas -> Panopto LTI 1.3 / OIDC authentication.

Ported from the proven standalone Panopto downloader, but parametrized by the
Canvas base URL + access token (no hardcoded institution) and made
host-agnostic: the Panopto host is derived from the final redirect URL rather
than hardcoded, so it works for any school using Canvas + Panopto LTI.

The handshake replicates what a browser does when a user clicks a Panopto link
in Canvas:
  1. Call the Canvas ``sessionless_launch`` API to get a one-time launch URL.
  2. GET it -> Canvas returns an auto-submit HTML form.
  3. POST the form through the OIDC chain until we land on the Panopto viewer,
     which sets Panopto session cookies.
"""

from __future__ import annotations

import html as _html
import logging
import re
from urllib.parse import unquote, urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

PANOPTO_ID_PATTERN = re.compile(
    r"(?:id|tid|custom_context_delivery)="
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
PANOPTO_FOLDER_PATTERN = re.compile(
    r"folderID=(?:%22|[\"'])?"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
# JSON/JS folder markers in a Panopto page body (List.aspx bootstraps its
# session list client-side; the folder id lives in embedded config, not the URL).
_BODY_FOLDER_PATTERN = re.compile(
    r"[\"']?folderId[\"']?\s*[:=]\s*[\"']"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


def extract_panopto_folder_id(url: str, body: str = "") -> str | None:
    """Best-effort Panopto FOLDER id from a landing URL and/or page body.

    The URL is checked raw and URL-decoded (the id often sits in a
    ``#folderID=%22<guid>%22`` fragment); the body is checked for both the
    link form (``folderID=``) and embedded config (``"folderId": "<guid>"``).
    """
    for text in (url or "", unquote(url or "")):
        m = PANOPTO_FOLDER_PATTERN.search(text)
        if m:
            return m.group(1).lower()
    if body:
        m = PANOPTO_FOLDER_PATTERN.search(body) or _BODY_FOLDER_PATTERN.search(body)
        if m:
            return m.group(1).lower()
    return None


def extract_panopto_ids(text: str) -> list[str]:
    """Return all Panopto GUIDs found in *text* (raw and URL-decoded).

    Decodes up to TWO unquote passes: a login/interstitial URL often carries the
    real target double-encoded (e.g. ``Login.aspx?ReturnUrl=...Viewer.aspx%253Fid
    %253D<guid>``), where a single unquote still leaves ``%3Fid%3D`` and the id
    pattern misses it.
    """
    if not text:
        return []
    ids = set()
    seen = text
    for _ in range(3):  # raw + 2 decode passes
        for m in PANOPTO_ID_PATTERN.finditer(seen):
            ids.add(m.group(1).lower())
        decoded = unquote(seen)
        if decoded == seen:
            break
        seen = decoded
    return list(ids)


# High-confidence body markers for the SESSION a Panopto page is about. Used
# only as a fallback when the final handshake URL itself carries no id.
_BODY_VIEWER_PATTERN = re.compile(
    r"(?:Viewer|Embed)\.aspx\?id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_BODY_DELIVERY_PATTERN = re.compile(
    r"(?:deliveryId|sessionId)[\"']?\s*[:=]\s*[\"']?"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


def _id_from_page_body(body: str) -> tuple[str | None, int]:
    """Best-effort session id from a Panopto PAGE BODY: ``(id, candidates)``.

    Some LTI landings never put the id in the URL - the viewer is reached via a
    JS redirect or the page embeds the delivery id only in its markup/config.
    Scan for high-confidence markers (Viewer/Embed links, deliveryId/sessionId
    assignments) and take the most frequent GUID. To avoid mis-attributing a
    FOLDER/list page (many session links, each mentioned ~once) to a single
    recording, the winner must either be the only unique GUID seen or be
    mentioned at least twice. Returns the number of distinct candidates for
    diagnostics.
    """
    if not body:
        return None, 0
    from collections import Counter
    counts: Counter = Counter()
    for pat in (_BODY_VIEWER_PATTERN, _BODY_DELIVERY_PATTERN):
        for m in pat.finditer(body):
            counts[m.group(1).lower()] += 1
    if not counts:
        return None, 0
    winner, hits = counts.most_common(1)[0]
    if len(counts) == 1 or hits >= 2:
        return winner, len(counts)
    return None, len(counts)


def panopto_base_from_url(url: str) -> str | None:
    """Derive the Panopto origin (scheme://host) from any Panopto URL."""
    if not url:
        return None
    try:
        p = urlparse(url)
        if p.scheme and p.netloc and "panopto" in p.netloc.lower():
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return None


def _session_auth_diag(session, panopto_base: str, body: str) -> str:
    """One-line auth-state diagnostic for a Panopto landing.

    Cookie NAMES only (never values), domain-matched to the Panopto host, plus
    anonymous-vs-authenticated markers scraped from the page body. Decisive
    for the "every call answers but every list/delivery comes back empty or
    denied" class: Panopto masks missing grants as empty results and 'session
    isn't available' errors, so whether the LTI handshake actually produced an
    authenticated session must be readable straight from the log.
    """
    try:
        host = (urlparse(panopto_base).hostname or "").lower()
    except Exception:
        host = ""
    names: set = set()
    try:
        for c in session.cookies:
            d = (getattr(c, "domain", "") or "").lstrip(".").lower()
            if d and host and (host == d or host.endswith("." + d)):
                names.add(c.name)
    except Exception:
        pass
    markers = []
    b = body or ""
    m = re.search(r'"IsAuthenticated"\s*:\s*(true|false)', b, re.IGNORECASE)
    if m:
        markers.append(f"IsAuthenticated={m.group(1).lower()}")
    if re.search(
        r'user[a-z]{0,12}["\']?\s*[:=]\s*["\']?0{8}-0{4}-0{4}-0{4}-0{12}',
        b, re.IGNORECASE,
    ):
        markers.append("anonymous-user-guid")
    if "Auth/Login.aspx" in b or "Pages/Auth/Login" in b:
        markers.append("login-link-present")
    return (f"cookies[{host or '?'}]=" + (",".join(sorted(names)) or "NONE")
            + " | markers=" + (",".join(markers) or "none"))


def parse_lti_form(html: str):
    """Extract (action, fields) from an auto-submit LTI form, or (None, None)."""
    m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not m:
        return None, None
    action = _html.unescape(m.group(1))
    form_data = {}
    for im in re.finditer(r"<input([^>]+)>", html, re.IGNORECASE):
        attrs = im.group(1)
        name_m = re.search(r'name=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        value_m = re.search(r'value=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        if name_m:
            form_data[name_m.group(1)] = (
                _html.unescape(value_m.group(1)) if value_m else ""
            )
    return action, form_data


def lti_launch(sessionless_launch_api_url: str, canvas_token: str, *, timeout: int = 20):
    """Run the full Canvas -> Panopto LTI handshake.

    Returns ``(session, final_url, real_video_id, panopto_base, folder_id)`` on
    success, or ``(None, None, None, None, None)`` on failure. ``session``
    carries the Panopto auth cookies needed for ``DeliveryInfo`` + folder APIs.
    ``folder_id`` is set when the launch landed on a Panopto FOLDER page (e.g.
    the Sessions/List.aspx course listing) instead of a single viewer - the
    caller can then enumerate that folder's sessions to resolve the recording.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        r = requests.get(
            sessionless_launch_api_url,
            headers={"Authorization": f"Bearer {canvas_token}"},
            timeout=timeout,
        )
        r.raise_for_status()
        launch_url = r.json().get("url", "")
    except Exception as e:
        logger.warning(f"Panopto LTI: sessionless_launch API failed: {e}")
        return None, None, None, None, None

    if not launch_url:
        logger.warning("Panopto LTI: sessionless_launch returned no launch URL.")
        return None, None, None, None, None

    def _loc(u: str) -> str:
        """host+path of *u* - never the query (it can carry auth material)."""
        try:
            p = urlparse(u)
            return f"{p.netloc}{p.path}"
        except Exception:
            return "?"

    try:
        r = session.get(launch_url, timeout=timeout, allow_redirects=True)
    except Exception as e:
        logger.warning(f"Panopto LTI: GET launch url failed: {e}")
        return None, None, None, None, None

    # Chain trace: one entry per hop (hosts+paths, form-field NAMES only).
    # Logged when the handshake fails to reach Panopto, so a dead chain is
    # diagnosable from debug_log.txt instead of just "landed on <page>".
    _trace = [f"GET->{getattr(r, 'status_code', '?')} {_loc(r.url)}"]

    # Follow the auto-submit form chain. 10 steps (was 6): some LTI 1.3 chains
    # (OIDC init -> authorize -> tool -> storage-access interstitials) are longer
    # than the classic flow, and the 2026-07-09 CBS run showed 30 links
    # EXHAUSTING the old budget ("6 redirect step(s)" with no id) while the
    # working ones finished in 2 - the chain wasn't done when we gave up.
    #
    # Loop-detection compares the FULL state (url, action, form fields): a
    # legitimate OIDC round-trip can revisit the same (url, action) pair with
    # fresh state/nonce fields and MUST be re-posted (a url+action-only
    # comparison broke the working auth bootstrap on the 2026-07-09 run - it
    # bailed on the first revisit and never reached Panopto). Only an IDENTICAL
    # re-serve twice in a row is a genuine dead loop. Separately, a form on a
    # Panopto host that posts back to ITS OWN page (e.g. Sessions/List.aspx's
    # search form) is terminal UI, never an LTI hop - stop immediately instead
    # of churning the budget on self-posts.
    from collections import Counter
    steps_used = 0
    _state_counts: Counter = Counter()
    for _step in range(10):
        # Terminal only when the HOST is a Panopto host: intermediate Canvas
        # hops (the tool page, /api/lti/authorize) carry the encoded Panopto
        # target - including a custom_context_delivery GUID on legacy links -
        # in their QUERY, so a substring/id check alone stops the chain one
        # hop early ("break:viewer" on a Canvas URL, no cookies, 0 downloads).
        if panopto_base_from_url(r.url) and (
            "Viewer.aspx" in r.url or "Embed.aspx" in r.url
            or extract_panopto_ids(r.url)
        ):
            _trace.append("break:viewer")
            break
        action, form_data = parse_lti_form(r.text)
        if not action:
            _trace.append(f"break:no-form ({len(r.text or '')} chars)")
            break
        action = urljoin(r.url, action)
        if (panopto_base_from_url(r.url)
                and action.split("?")[0] == r.url.split("?")[0]):
            _trace.append("break:self-post")
            break
        _state = (r.url, action, tuple(sorted((form_data or {}).items())))
        _state_counts[_state] += 1
        if _state_counts[_state] >= 3:
            logger.info("Panopto LTI: form chain stopped advancing at %s "
                        "(action %s, identical form re-served) - breaking "
                        "after %d step(s).",
                        r.url.split("?")[0], action.split("?")[0], steps_used)
            _trace.append("break:dead-loop")
            break
        steps_used += 1
        try:
            r = session.post(action, data=form_data, timeout=timeout, allow_redirects=True)
        except Exception as e:
            logger.warning(f"Panopto LTI: OIDC POST step {steps_used} failed: {e}")
            return None, None, None, None, None
        _trace.append(
            f"POST {_loc(action)} "
            f"[{','.join(sorted((form_data or {}).keys()))[:160]}] "
            f"->{getattr(r, 'status_code', '?')} {_loc(r.url)}"
        )

    panopto_base = panopto_base_from_url(r.url)
    real_ids = extract_panopto_ids(r.url)
    real_video_id = real_ids[0] if real_ids else None

    body_candidates = 0
    folder_id = None
    resolved_via = "url" if real_video_id else None
    if panopto_base and not real_video_id:
        # The URL carries no id - some landings only reference the session in
        # the page body (JS redirect to Viewer.aspx, embedded delivery config).
        real_video_id, body_candidates = _id_from_page_body(r.text or "")
        if real_video_id:
            resolved_via = "body"
        else:
            # No single session either - a folder landing (course session
            # list). Surface its folder id so the caller can enumerate the
            # folder's sessions and resolve the recording by title.
            folder_id = extract_panopto_folder_id(r.url, r.text or "")

    if panopto_base:
        logger.info(
            "Panopto LTI handshake OK (%d redirect step(s)); host=%s, resolved_id=%s%s",
            steps_used, panopto_base, real_video_id or "none",
            f" (via {resolved_via})" if real_video_id else "",
        )
        if not real_video_id:
            # Diagnostics for the "link exists but no recording found" class:
            # WHERE did we land, was a form left unfollowed (chain too short /
            # stuck), did the body mention any candidate sessions, and did the
            # landing reveal a folder we can enumerate instead? Path only -
            # the query string can carry auth material.
            _leftover_action, _ = parse_lti_form(r.text or "")
            logger.info(
                "Panopto LTI: no session id resolved - landed on %s | "
                "unfollowed form: %s | body: %d chars, %d candidate id(s) | "
                "folder: %s | auth: %s",
                r.url.split("?")[0] if r.url else "?",
                (_leftover_action or "none").split("?")[0],
                len(r.text or ""), body_candidates,
                folder_id or "none",
                _session_auth_diag(session, panopto_base, r.text or ""),
            )
    else:
        logger.warning(
            "Panopto LTI handshake did not reach a Panopto host (landed on %s). "
            "Cookies may be missing - downloads will likely fail. Chain: %s",
            r.url.split("?")[0] if r.url else "?",
            " | ".join(_trace),
        )
    return session, r.url, real_video_id, panopto_base, folder_id
