"""Does THIS Canvas institution use Panopto at all, and which LTI tool is it?

Answers one cheap question so the rest of the Panopto pipeline can be skipped
entirely at universities that do not use it. Measured against a real Canvas
(CBS, 33 courses) on 2026-07-31:

* ``GET /courses/:id/external_tools?include_parents=true`` returns **200 for an
  ordinary student token** and lists the account-level tools. Panopto appeared in
  **33/33** courses with ``context: null``, i.e. it is installed once at the
  ACCOUNT level and inherited by every course.
* ``GET /accounts/self/external_tools`` returns **403** for a student, so the
  lookup MUST go through a course id. Any single course answers for the whole
  institution.
* Without ``include_parents`` the same endpoint returns **zero** tools in every
  course, so it is useless on its own.
* ``GET /courses/:id/tabs`` does not list Panopto even where the tool is enabled,
  so it is not a usable detector either.
* Cost: ~227 ms average, 686 ms worst case. Once per session.

**This tells you whether the INSTITUTION has Panopto. It can never tell you
whether a given COURSE has recordings** - every course returns the same
account-wide list. Only the module scan can answer that.

## Why there is no hardcoded tool id anywhere in here

The Panopto tool at CBS is id ``863``. That number is a Canvas autoincrement
primary key and is **different at every institution**. Matching on it would make
the feature work at exactly one university and silently do nothing everywhere
else - a failure with no error message, no log line and no user-visible symptom.
Ids are always RESOLVED at runtime from :func:`looks_panopto`.

## Why the matcher is a union of three fields

Measured shapes from the same probe:

* ``name`` "Panopto videos", ``domain`` "cbs.cloud.panopto.eu",
  ``url`` "https://cbs.cloud.panopto.eu/Panopto/LTI/LTI.aspx".
* **7 of the 23 tools have a NULL ``domain``** (Attendance, Chat, Course
  Readings, OneNote, Pearson, Piazza, Quizzes 2). An unguarded
  ``t["domain"].lower()`` raises - it did, on the first version of the probe.
* An institution may front Panopto with a vanity CNAME (``video.uni.edu``),
  exactly as ``panopto/stream.py:_cookie_header`` already handles for cookies.
  There the domain carries no "panopto" substring - but the LTI launch path
  ``/Panopto/LTI/LTI.aspx`` does, because that path is Panopto's own product
  route rather than the customer's hostname. Matching the URL is what keeps
  vanity-hosted institutions working.

So: name OR domain OR url, every field ``None``-safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Substring that identifies Panopto in a tool's name, domain or URL. The URL
#: form additionally matches the product path ("/panopto/") which survives a
#: vanity hostname.
_PANOPTO_MARK = "panopto"


@dataclass(frozen=True)
class ToolScan:
    """What one institution-level external-tool lookup told us.

    ``resolved`` is False when the lookup could not be completed (network error,
    no course id, unexpected payload). Callers must then behave as if Panopto
    MIGHT be present - see :meth:`should_skip_panopto`.
    """

    resolved: bool = False
    has_panopto: bool = False
    #: Ids of tools that matched the Panopto marker, resolved at runtime.
    panopto_tool_ids: frozenset = field(default_factory=frozenset)
    #: Every tool id the institution exposes. Anything in here but NOT in
    #: ``panopto_tool_ids`` is PROVABLY not Panopto, which is what makes the
    #: module-item handshake filter safe.
    known_tool_ids: frozenset = field(default_factory=frozenset)

    def should_skip_panopto(self) -> bool:
        """True only when we positively established the institution has no Panopto.

        An unresolved scan returns False (do NOT skip). Failing open matters:
        a transient network error must never silently remove a feature the user
        configured, and the only cost of guessing "present" is one dialog and a
        discovery pass that finds nothing.
        """
        return self.resolved and not self.has_panopto

    def is_known_non_panopto_tool(self, tool_id) -> bool:
        """True when *tool_id* is a tool we listed and it is NOT Panopto.

        The one question the handshake filter is allowed to ask. An id we never
        saw (or ``None``) returns False, so an unrecognised item still gets its
        LTI handshake and can never be lost.
        """
        if not self.resolved or tool_id is None:
            return False
        try:
            tid = int(tool_id)
        except (TypeError, ValueError):
            return False
        return tid in self.known_tool_ids and tid not in self.panopto_tool_ids


def looks_panopto(tool: dict) -> bool:
    """True when an external-tool record is Panopto. Never raises.

    Union over name / domain / url because no single field is reliable across
    institutions (see the module docstring). Every field is coerced through
    ``or ""`` - a null ``domain`` is common, not exotic.
    """
    if not isinstance(tool, dict):
        return False
    for key in ("name", "domain", "url"):
        if _PANOPTO_MARK in str(tool.get(key) or "").lower():
            return True
    return False


#: Resolved scans, keyed by Canvas host. Safe to share across sessions because
#: the answer describes the INSTITUTION, not the user - every account on one
#: Canvas sees the same account-level tool list (verified: identical result from
#: two different courses). Without this, discovery would pay the lookup once per
#: COURSE; with 33 courses that is ~7.6s of pure latency to learn one fact.
_SCAN_MEMO: dict = {}


def cached_scan(rest, course_id) -> ToolScan:
    """:func:`scan_external_tools`, resolved at most once per Canvas host.

    Only RESOLVED scans are memoised, so a transient failure is retried rather
    than frozen into "unknown" for the life of the process.
    """
    key = getattr(rest, "base", None) or ""
    if not key:
        # No host to key on. Caching under "" would make one institution's
        # answer apply to the next, which for this fact means silently
        # disabling Panopto for a university that has it (or the reverse).
        return scan_external_tools(rest, course_id)
    hit = _SCAN_MEMO.get(key)
    if isinstance(hit, ToolScan) and hit.resolved:
        return hit
    scan = scan_external_tools(rest, course_id)
    if scan.resolved:
        _SCAN_MEMO[key] = scan
    return scan


def scan_external_tools(rest, course_id) -> ToolScan:
    """Resolve the institution's Panopto tools via ONE course.

    Args:
        rest: a ``panopto.discovery._CanvasREST``-shaped client (``get_all``).
        course_id: any course the user is enrolled in. The account-level list is
            identical for all of them, so the choice does not matter.

    Returns a :class:`ToolScan`. Never raises: every failure path yields an
    unresolved scan, which callers treat as "Panopto might be present".
    """
    if not course_id:
        return ToolScan()
    try:
        tools = rest.get_all(
            f"/api/v1/courses/{course_id}/external_tools",
            {"include_parents": "true"},
        )
    except Exception as e:  # pragma: no cover - get_all already swallows
        logger.debug("Panopto institution scan failed for course %s: %s", course_id, e)
        return ToolScan()

    if not isinstance(tools, list) or not tools:
        # An empty list is genuinely ambiguous: it is what a course returns
        # WITHOUT include_parents, and also what a 401/403 degrades to. Refuse to
        # conclude "no Panopto" from it.
        logger.info("Panopto institution scan: no tools listed for course %s.", course_id)
        return ToolScan()

    pan_ids, all_ids = set(), set()
    for t in tools:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            tid = None
        if tid is not None:
            all_ids.add(tid)
        if looks_panopto(t):
            if tid is not None:
                pan_ids.add(tid)

    has = bool(pan_ids) or any(looks_panopto(t) for t in tools if isinstance(t, dict))
    logger.info(
        "Panopto institution scan: %d tool(s), Panopto=%s (ids=%s)",
        len(all_ids), has, sorted(pan_ids) or "-",
    )
    return ToolScan(
        resolved=True,
        has_panopto=has,
        panopto_tool_ids=frozenset(pan_ids),
        known_tool_ids=frozenset(all_ids),
    )
