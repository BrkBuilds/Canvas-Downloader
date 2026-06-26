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
    """Return all Panopto GUIDs found in *text* (raw and URL-decoded)."""
    if not text:
        return []
    ids = set()
    for m in PANOPTO_ID_PATTERN.finditer(text):
        ids.add(m.group(1).lower())
    decoded = unquote(text)
    if decoded != text:
        for m in PANOPTO_ID_PATTERN.finditer(decoded):
            ids.add(m.group(1).lower())
    return list(ids)


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

    steps_used = 0
    for _step in range(6):
        if "panopto" in r.url.lower() and (
            "Viewer.aspx" in r.url or "Embed.aspx" in r.url
        ):
            break
        action, form_data = parse_lti_form(r.text)
        if not action:
            break
        action = urljoin(r.url, action)
        steps_used += 1
        try:
            r = session.post(action, data=form_data, timeout=timeout, allow_redirects=True)
        except Exception as e:
            logger.warning(f"Panopto LTI: OIDC POST step {steps_used} failed: {e}")
            return None, None, None, None

    panopto_base = panopto_base_from_url(r.url)
    real_ids = extract_panopto_ids(r.url)
    real_video_id = real_ids[0] if real_ids else None
    if panopto_base:
        logger.info(
            "Panopto LTI handshake OK (%d redirect step(s)); host=%s, resolved_id=%s",
            steps_used, panopto_base, real_video_id or "none",
        )
    else:
        logger.warning(
            "Panopto LTI handshake did not reach a Panopto host (landed on %s). "
            "Cookies may be missing - downloads will likely fail.",
            r.url.split("?")[0] if r.url else "?",
        )
    return session, r.url, real_video_id, panopto_base
