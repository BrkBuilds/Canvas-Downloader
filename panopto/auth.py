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
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

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


#: A Panopto HOST, recognised by the product route that follows it. The path
#: ``/Panopto/`` is Panopto's own, so it survives a vanity CNAME (``video.uni.edu``)
#: where the hostname carries no "panopto" substring at all - the same reasoning
#: ``panopto.institution`` uses to identify the LTI tool.
#:
#: The host class excludes ``/`` on purpose. Allowing it (with a lazy quantifier)
#: still matches, but it matches from the FIRST scheme in the text: a Canvas
#: ``external_tools/retrieve?url=https://host/Panopto/...`` link then yields
#: ``https://canvas.edu/courses/1/external_tools/retrieve?url=https://host`` -
#: a string that looks like a URL, passes every truthiness check, and produces a
#: shortcut pointing at nothing. Barring the separator makes the group a
#: hostname and nothing else.
_PANOPTO_HOST_PATTERN = re.compile(
    r"""(https?://[^\s"'<>\\/]+)/Panopto/""", re.IGNORECASE)


def extract_panopto_host(text: str) -> str | None:
    """Return the Panopto base URL (``https://host``) found in *text*, or None.

    Same raw + two-decode-pass sweep as :func:`extract_panopto_ids`, because the
    host arrives in the same places and just as often encoded: a Canvas
    ``external_tools/retrieve?url=https%3A%2F%2Fhost%2FPanopto%2F...`` link hides
    it behind one pass, an interstitial login behind two.

    Returned without a trailing slash, which is the shape every consumer expects
    (``panopto.stream`` builds ``f"{base}/Panopto/Pages/Viewer.aspx"``).
    """
    if not text:
        return None
    seen = text
    for _ in range(3):  # raw + 2 decode passes
        m = _PANOPTO_HOST_PATTERN.search(seen)
        if m:
            return m.group(1).rstrip("/")
        decoded = unquote(seen)
        if decoded == seen:
            break
        seen = decoded
    return None


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


# A Panopto server is identified two ways, because the hostname alone is not
# reliable across institutions:
#   * HOST marker - the cloud tenants carry "panopto" in the host itself
#     (``<name>.hosted.panopto.com``, ``<name>.cloud.panopto.eu``, or a plain
#     ``panopto.university.edu``).
#   * PATH marker - Panopto's web application is ALWAYS mounted at the
#     ``/Panopto/`` product route (Viewer.aspx, Embed.aspx, DeliveryInfo.aspx,
#     LTI/LTI.aspx, api/v1 and Services/Data.svc all live beneath it), whatever
#     hostname the customer fronts it with. This is what recognises a vanity
#     CNAME (``video.university.edu``) or an on-prem install on a fully custom
#     domain, whose host carries no "panopto" at all.
# Matching only the host silently failed EVERY download for a vanity/on-prem
# institution even though the LTI session was valid: ``panopto_base`` came back
# None, so the runner concluded "no Panopto session" and the whole course failed
# with nothing actionable in the log. ``institution.py`` (LTI tool match) and
# ``stream.py`` (cookie domain match) already key off the path/domain for exactly
# this reason - this closes the last host-only gate so the three agree.
_PANOPTO_HOST_MARK = "panopto"
_PANOPTO_ROUTE_MARK = "/panopto/"


def _is_panopto_location(netloc: str, path: str) -> bool:
    """True when a URL's (host, path) belongs to a Panopto server. Never raises.

    The path test is applied to the PATH ONLY - never the query - so a Canvas
    OIDC hop that carries the encoded Panopto target
    (``redirect_uri=...%2FPanopto%2FLTI.aspx``) in its query string is correctly
    NOT mistaken for a Panopto landing (which would break the handshake one hop
    early, on a Canvas URL, with no cookies). A trailing slash is appended before
    matching so a bare ``/Panopto`` still counts while ``/Panoptolike/...`` on
    some unrelated host does not.
    """
    if _PANOPTO_HOST_MARK in (netloc or "").lower():
        return True
    return _PANOPTO_ROUTE_MARK in ((path or "").lower() + "/")


def panopto_base_from_url(url: str) -> str | None:
    """Derive the Panopto origin (``scheme://host``) from any Panopto URL.

    Recognises the host by the "panopto" marker in the hostname (cloud tenants)
    OR by the ``/Panopto/`` product route in the path (vanity CNAMEs and on-prem
    installs on a custom domain). Returns None for anything not identifiably
    Panopto.
    """
    if not url:
        return None
    try:
        p = urlparse(url)
        if p.scheme and p.netloc and _is_panopto_location(p.netloc, p.path):
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


def in_app_launch_url(sessionless_launch_api_url: str) -> str:
    """The IN-APP equivalent of a ``sessionless_launch`` API URL, or ``""``.

    **Canvas refuses ``sessionless_launch`` to anything but an access token**,
    and that is Canvas' own rule, not a permission quirk of one course
    (``app/controllers/lti/concerns/sessionless_launches.rb``)::

        def generate_session_token
          # only allow from API, and not from files domain
          raise UnauthorizedClient unless @access_token

    Measured against real Canvas on a browser session: **every** launch, on all
    36 Panopto items of one course and in both URL shapes, answered
    ``403 user not authorised to perform that action`` - while ``users/self``
    and the Files API on the SAME session answered 200. So a browser-session
    user would get no recordings, no transcripts and no subtitles at all.

    A student watching that lecture in a browser is not doing anything
    exotic, though: they click the module item, and Canvas performs the LTI
    launch from their session. That route is open to us for the same reason,
    and the three shapes below are the in-app equivalents of the three
    ``sessionless_launch`` URLs this app builds. All three were driven end to
    end on a real session (3 hops each, landing on the Panopto host with
    ``.ASPXAUTH`` and no Canvas cookie reaching Panopto):

    ==========================================  ============================================
    ``sessionless_launch?...``                  in-app
    ==========================================  ============================================
    ``launch_type=module_item&module_item_id``  ``/courses/<cid>/modules/items/<item_id>``
    ``?id=<tool>&url=<tool url>``               ``/courses/<cid>/external_tools/retrieve?url=``
    ``?id=<tool>``                              ``/courses/<cid>/external_tools/<tool_id>``
    ==========================================  ============================================

    Only the module-item form lands on the RECORDING (its delivery id is in the
    URL); the other two land on the course FOLDER, which is exactly what their
    sessionless counterparts do as well.
    """
    try:
        parsed = urlparse(sessionless_launch_api_url or "")
        params = parse_qs(parsed.query)
        base = f"{parsed.scheme}://{parsed.netloc}"
        parts = parsed.path.strip("/").split("/")
        # .../api/v1/courses/<cid>/external_tools/sessionless_launch
        if "courses" not in parts:
            return ""
        cid = parts[parts.index("courses") + 1]
        if not cid:
            return ""
        item_id = (params.get("module_item_id") or [""])[0]
        if item_id:
            return f"{base}/courses/{cid}/modules/items/{item_id}"
        tool_url = (params.get("url") or [""])[0]
        if tool_url:
            return (f"{base}/courses/{cid}/external_tools/retrieve"
                    f"?url={quote(tool_url, safe='')}")
        tool_id = (params.get("id") or [""])[0]
        if tool_id:
            return f"{base}/courses/{cid}/external_tools/{tool_id}"
    except Exception as e:                                         # noqa: BLE001
        logger.warning("Could not derive an in-app launch URL from %r: %s",
                       sessionless_launch_api_url, e, exc_info=True)
    return ""


def lti_launch(sessionless_launch_api_url: str, canvas_credential, *, timeout: int = 20):
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

    # This one call is to CANVAS, not Panopto, so it carries the Canvas
    # credential - a bearer, or a host-scoped session cookie jar. `session`
    # above is the PANOPTO session and stays untouched: the handshake below
    # earns its own cookies, and mixing the two would send a Canvas login to
    # a Panopto host. See core/canvas_auth.py.
    from core.canvas_auth import coerce as _coerce_credential
    _canvas_cred = _coerce_credential(canvas_credential, sessionless_launch_api_url)

    launch_url = ""
    if _canvas_cred.is_browser:
        # Canvas will not mint a sessionless launch for a session cookie at all
        # (see in_app_launch_url), so take the route a student's own click
        # takes. The Canvas cookies ride on the PANOPTO session's jar, which is
        # safe for one measured reason: they are installed with an explicit
        # DOMAIN, so requests drops them at the first Panopto hop. Verified on a
        # real launch - Panopto received none of them. Only the cookies are
        # copied, never the User-Agent, so the handshake keeps the UA it has
        # always sent.
        launch_url = in_app_launch_url(sessionless_launch_api_url)
        if launch_url:
            _jar = _canvas_cred.requests_cookie_jar()
            if _jar is not None:
                session.cookies.update(_jar)
        else:
            logger.warning("Panopto LTI: no in-app launch URL could be derived "
                           "from %s; falling back to the API form, which Canvas "
                           "refuses for a browser session.",
                           sessionless_launch_api_url.split("?")[0])

    if not launch_url:
        try:
            r = requests.get(
                sessionless_launch_api_url,
                headers=_canvas_cred.auth_headers(),
                cookies=_canvas_cred.requests_cookie_jar(),
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

    # An expired BROWSER SESSION does not 401 here - Canvas redirects the
    # module-item page to /login and on to the institution's identity provider,
    # which answers 200 with a login form. The form-chain walker below would
    # then dutifully try to submit the IdP's sign-in form, exhaust its ten
    # steps, and report "no delivery id" - i.e. "this course has no
    # recordings", which is the wrong answer to "you are signed out" and the
    # only one a user would ever see. Raised, not returned, so it reaches the
    # same reconnect routing as every other 401 in the app.
    from core.canvas_auth import is_login_redirect as _is_login_redirect
    from core.canvas_auth import visited_urls as _visited_urls
    if _is_login_redirect(_visited_urls(r)):
        from core.canvas_logic import CanvasSessionExpired
        raise CanvasSessionExpired(
            "Canvas asked for a sign-in instead of starting the Panopto launch "
            "(401 - the session has expired)."
        )

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
