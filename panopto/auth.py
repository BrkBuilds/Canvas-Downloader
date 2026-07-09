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
    r"folderID=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


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

    Returns ``(session, final_url, real_video_id, panopto_base)`` on success, or
    ``(None, None, None, None)`` on failure. ``session`` carries the Panopto
    auth cookies needed for ``DeliveryInfo`` + folder APIs.
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
        return None, None, None, None

    if not launch_url:
        logger.warning("Panopto LTI: sessionless_launch returned no launch URL.")
        return None, None, None, None

    try:
        r = session.get(launch_url, timeout=timeout, allow_redirects=True)
    except Exception as e:
        logger.warning(f"Panopto LTI: GET launch url failed: {e}")
        return None, None, None, None

    # Follow the auto-submit form chain. 10 steps (was 6): some LTI 1.3 chains
    # (OIDC init -> authorize -> tool -> storage-access interstitials) are longer
    # than the classic flow, and the 2026-07-09 CBS run showed 30 links
    # EXHAUSTING the old budget ("6 redirect step(s)" with no id) while the
    # working ones finished in 2 - the chain wasn't done when we gave up.
    # Loop-detection stops re-posting a page that no longer advances (e.g. a
    # search/login form our first-<form> parser latched onto), so a genuine
    # dead-end no longer burns the whole budget.
    steps_used = 0
    _prev_state = None
    for _step in range(10):
        if "panopto" in r.url.lower() and (
            "Viewer.aspx" in r.url or "Embed.aspx" in r.url
            or extract_panopto_ids(r.url)
        ):
            break
        action, form_data = parse_lti_form(r.text)
        if not action:
            break
        action = urljoin(r.url, action)
        _state = (r.url, action)
        if _state == _prev_state:
            logger.debug("Panopto LTI: form chain stopped advancing at %s "
                         "(action %s) - breaking.",
                         r.url.split("?")[0], action.split("?")[0])
            break
        _prev_state = _state
        steps_used += 1
        try:
            r = session.post(action, data=form_data, timeout=timeout, allow_redirects=True)
        except Exception as e:
            logger.warning(f"Panopto LTI: OIDC POST step {steps_used} failed: {e}")
            return None, None, None, None

    panopto_base = panopto_base_from_url(r.url)
    real_ids = extract_panopto_ids(r.url)
    real_video_id = real_ids[0] if real_ids else None

    body_candidates = 0
    resolved_via = "url" if real_video_id else None
    if panopto_base and not real_video_id:
        # The URL carries no id - some landings only reference the session in
        # the page body (JS redirect to Viewer.aspx, embedded delivery config).
        real_video_id, body_candidates = _id_from_page_body(r.text or "")
        if real_video_id:
            resolved_via = "body"

    if panopto_base:
        logger.info(
            "Panopto LTI handshake OK (%d redirect step(s)); host=%s, resolved_id=%s%s",
            steps_used, panopto_base, real_video_id or "none",
            f" (via {resolved_via})" if real_video_id else "",
        )
        if not real_video_id:
            # Diagnostics for the "link exists but no recording found" class:
            # WHERE did we land, was a form left unfollowed (chain too short /
            # stuck), and did the body mention any candidate sessions? Path
            # only - the query string can carry auth material.
            _leftover_action, _ = parse_lti_form(r.text or "")
            logger.info(
                "Panopto LTI: no session id resolved - landed on %s | "
                "unfollowed form: %s | body: %d chars, %d candidate id(s)",
                r.url.split("?")[0] if r.url else "?",
                (_leftover_action or "none").split("?")[0],
                len(r.text or ""), body_candidates,
            )
    else:
        logger.warning(
            "Panopto LTI handshake did not reach a Panopto host (landed on %s). "
            "Cookies may be missing - downloads will likely fail.",
            r.url.split("?")[0] if r.url else "?",
        )
    return session, r.url, real_video_id, panopto_base
