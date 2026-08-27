"""Submit changed site URLs to IndexNow (Bing, Yandex, Seznam, Naver).

WHY THIS EXISTS
    Hosting the key file is only half of IndexNow. Bing's IndexNow page stays on
    its setup screen until it receives a first successful SUBMISSION, and until
    2026-08-27 nothing in this repo ever submitted. The key had been live and
    correct for days while the feature was inert.

    It matters more than its size suggests: Bing feeds Copilot and ChatGPT
    search, which is the surface `docs/llms.txt` was written for, and Bing had
    crawled the site exactly once (23 Aug) at the time this was written.

THE KEY IS DERIVED, NEVER RESTATED
    `find_key()` globs `docs/` for the 32-hex `.txt` file whose CONTENT equals
    its own stem, which is what the IndexNow spec requires of a key file. So the
    key exists in exactly one place: the file itself. Hardcoding it here would
    be a second copy of one fact, and this repo has been bitten by that three
    times (`make_long_path`'s duplicate, the three AppleScript escapers, the
    six-site module-item scope rule).

SUBMIT WHAT CHANGED, NOT EVERYTHING
    The spec asks for changed URLs. Re-submitting an unchanged set on every push
    is what the receiving engines treat as noise, so `--changed-since <ref>`
    maps `git diff` output onto site URLs and submits only those. The full
    sitemap is the deliberate exception for a first activation and for a manual
    resubmit, which is why it takes an explicit `--all`.

FAILING IS LOUD ON PURPOSE
    A ping that silently no-ops is exactly the state this script was written to
    end, so a genuine rejection exits non-zero. The key-file pre-check runs
    first because an unreachable or mismatched key is the single most common
    cause of a rejected submission, and its error message is otherwise opaque.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
HOST = "canvasdownloader.app"
ORIGIN = f"https://{HOST}"
ENDPOINT = "https://api.indexnow.org/IndexNow"

# A key file is 8-128 hex characters per the spec; this site's is 32.
_KEY_NAME = re.compile(r"^[a-f0-9]{8,128}$", re.IGNORECASE)

# Pages that must never be announced: both are per-visit confirmations carrying
# their own noindex, and robots.txt disallows them. 404 is not a page.
_NEVER_SUBMIT = {"thanks-win.html", "thanks-mac.html", "404.html"}

_TIMEOUT = 30
_RETRIES = 3


def find_key() -> tuple[str, str]:
    """Return (key, key_location) read from the one key file in docs/.

    The content must equal the stem. A file that merely looks like a key but
    holds something else would be rejected by the endpoint with a message that
    does not say why, so it is caught here instead.
    """
    candidates = []
    for path in sorted(DOCS.glob("*.txt")):
        if not _KEY_NAME.match(path.stem):
            continue
        body = path.read_text(encoding="utf-8").strip()
        if body == path.stem:
            candidates.append(path)

    if not candidates:
        raise SystemExit(
            "No IndexNow key file in docs/. Expected a file named <key>.txt "
            "whose only content is <key>. Generate one at "
            "https://www.bing.com/indexnow/getstarted"
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise SystemExit(f"More than one IndexNow key file in docs/: {names}")

    key = candidates[0].stem
    return key, f"{ORIGIN}/{candidates[0].name}"


def verify_key_is_live(key_location: str) -> None:
    """Fail fast if the key file is not reachable and correct at its URL."""
    try:
        with urllib.request.urlopen(key_location, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8").strip()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Key file {key_location} returned HTTP {exc.code}.")
    except OSError as exc:
        raise SystemExit(f"Could not fetch key file {key_location}: {exc}")

    expected = key_location.rsplit("/", 1)[-1][: -len(".txt")]
    if status != 200 or body != expected:
        raise SystemExit(
            f"Key file {key_location} is not valid "
            f"(HTTP {status}, body {body!r}, expected {expected!r})."
        )


def urls_from_sitemap() -> list[str]:
    text = (DOCS / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.S)


def _page_to_url(rel: str) -> str | None:
    """Map a repo path like docs/blog.html onto its public URL."""
    if not rel.startswith("docs/") or not rel.endswith(".html"):
        return None
    name = rel[len("docs/"):]
    if "/" in name or name in _NEVER_SUBMIT:
        return None
    if name == "index.html":
        return f"{ORIGIN}/"
    return f"{ORIGIN}/{name}"


def _resolve_base(base_ref: str) -> str:
    """Fall back to HEAD~1 when the ref is unusable.

    A push event hands us all-zeros for a new branch, and a force-push can name
    a commit this checkout does not have. Both are ordinary; neither should
    abort the ping, because the alternative is announcing nothing at all.
    """
    if set(base_ref) == {"0"}:
        return "HEAD~1"
    ok = subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}^{{commit}}"],
        cwd=REPO_ROOT, capture_output=True,
    ).returncode == 0
    return base_ref if ok else "HEAD~1"


def changed_urls(base_ref: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", _resolve_base(base_ref), "HEAD", "--", "docs/"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    seen: list[str] = []
    for line in out.splitlines():
        url = _page_to_url(line.strip())
        if url and url not in seen:
            seen.append(url)
    return seen


def _is_live(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except OSError as exc:
        return False, f"unreachable ({exc})"


def live_urls(urls: list[str], wait_seconds: int = 0) -> list[str]:
    """Drop anything that does not answer 200, optionally waiting for deploys.

    Announcing a 404 is worse than announcing nothing, and this is not
    hypothetical here: on 2026-08-27 the working tree's sitemap listed
    download-lecture-videos-from-canvas.html while that page 404'd, and this
    check is what kept it out of the first submission.

    `wait_seconds` exists for CI. A push fires this workflow immediately but
    GitHub Pages takes a little while to publish, so a freshly-committed page is
    briefly absent for a reason that WILL resolve on its own. Waiting a bounded
    time distinguishes that from a page which is genuinely not there, without
    ever blocking forever.
    """
    deadline = time.monotonic() + wait_seconds
    pending = list(urls)
    ok: list[str] = []
    reasons: dict[str, str] = {}

    while True:
        still: list[str] = []
        for url in pending:
            good, why = _is_live(url)
            (ok if good else still).append(url)
            if not good:
                reasons[url] = why
        pending = still
        if not pending or time.monotonic() >= deadline:
            break
        print(f"  waiting for {len(pending)} URL(s) to publish...")
        time.sleep(15)

    for url in pending:
        print(f"  skipping ({reasons[url]}): {url}")
    # Preserve the caller's ordering rather than completion order.
    return [u for u in urls if u in set(ok)]


def submit(key: str, key_location: str, urls: list[str]) -> None:
    payload = json.dumps({
        "host": HOST,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }).encode("utf-8")

    req = urllib.request.Request(
        ENDPOINT, data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    last = ""
    for attempt in range(1, _RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                # 200 accepted, 202 accepted but key still being validated.
                if resp.status in (200, 202):
                    print(f"IndexNow accepted {len(urls)} URL(s): HTTP {resp.status}")
                    return
                last = f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()
            last = f"HTTP {exc.code} {detail}"
            # 4xx is our fault and will not fix itself; do not retry it.
            if 400 <= exc.code < 500:
                break
        except OSError as exc:
            last = str(exc)

        if attempt < _RETRIES:
            time.sleep(2 * attempt)

    raise SystemExit(f"IndexNow submission failed: {last}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Submit site URLs to IndexNow.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true",
                       help="submit every URL in docs/sitemap.xml (first activation, manual resubmit)")
    group.add_argument("--changed-since", metavar="REF",
                       help="submit only pages changed between REF and HEAD")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be submitted and exit")
    ap.add_argument("--wait-seconds", type=int, default=0, metavar="N",
                    help="wait up to N seconds for changed pages to publish (for CI)")
    args = ap.parse_args(argv)

    key, key_location = find_key()
    print(f"key file: {key_location}")

    urls = urls_from_sitemap() if args.all else changed_urls(args.changed_since)
    if not urls:
        print("No changed pages to submit. Nothing to do.")
        return 0

    print(f"candidates ({len(urls)}):")
    for url in urls:
        print(f"  {url}")

    if args.dry_run:
        print("\n--dry-run: not submitting.")
        return 0

    verify_key_is_live(key_location)
    urls = live_urls(urls, args.wait_seconds)
    if not urls:
        print("Nothing left to submit after the liveness check.")
        return 0

    submit(key, key_location, urls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
