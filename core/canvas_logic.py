import os
import platform
import re
import ssl
import uuid
import shutil
import hashlib
import html
import urllib.parse
import unicodedata
from pathlib import Path, PurePath
from datetime import datetime, timezone
from canvasapi import Canvas
from canvasapi.exceptions import (CanvasException, Forbidden,
                                  ResourceDoesNotExist, Unauthorized)
import asyncio
import aiohttp
import types
import threading
import aiofiles
from core.canvas_debug import log_debug
import logging
import requests
from requests.adapters import HTTPAdapter

from core.sync_manager import (
    SyncManager, make_secondary_id, is_secondary_id, CanvasFileInfo,
    preferred_disk_name, secondary_content_sig, secondary_id_type,
    secondary_raw_id,
)
from shared.helpers import make_long_path, path_exists, _err_log_lock

logger = logging.getLogger(__name__)


class _CanvasTimeoutAdapter(HTTPAdapter):
    """Injects a default (connect, read) timeout into every synchronous canvasapi request.

    Without this, course.get_modules() / course.get_files() etc. can hang
    indefinitely on high-latency or unreliable connections (e.g. cross-continent).
    The timeout causes requests.exceptions.Timeout to propagate through canvasapi,
    which then surfaces as a proper error rather than a silent hang.
    """
    def send(self, request, **kwargs):
        # 15s connect / 60s read. Slow Canvas servers on registration day may
        # exceed this; expose CANVAS_TIMEOUT env var if a user needs more time.
        kwargs.setdefault('timeout', (15, int(os.environ.get('CANVAS_TIMEOUT', 60))))
        return super().send(request, **kwargs)


# --- TLS trust store (critical on frozen macOS builds) ---
# canvasapi/requests verify TLS against certifi's bundled CA file, but aiohttp
# uses Python's default ssl context, which reads the OpenSSL default cert paths.
# Inside a PyInstaller .app on macOS those paths point at the *build* machine's
# Python install and don't exist on the user's machine, so every aiohttp file
# download fails with SSLCertVerificationError ("unable to get local issuer
# certificate") while API calls keep working. Build one shared context from
# certifi so both stacks trust the same CAs.
_ssl_context_cache: ssl.SSLContext | None = None

def get_ssl_context() -> ssl.SSLContext:
    """Return a cached SSLContext that verifies against certifi's CA bundle."""
    global _ssl_context_cache
    if _ssl_context_cache is None:
        try:
            import certifi
            _ssl_context_cache = ssl.create_default_context(cafile=certifi.where())
        except Exception as e:  # certifi missing/unreadable - system trust store fallback
            logger.warning(f"certifi unavailable ({e}); falling back to system SSL defaults")
            _ssl_context_cache = ssl.create_default_context()
    return _ssl_context_cache


# --- Global Async Locks ---
# Lock objects are event-loop-bound; only store reference counts and loop IDs
# at module level. New asyncio.Lock() objects are created per-loop to avoid
# "Task got Future attached to a different loop" across asyncio.run() calls.
_download_locks: dict = {}  # filepath -> {"lock": asyncio.Lock, "count": int, "loop_id": int}
_lock_mutex_local = threading.Lock()  # threading.Lock is loop-independent

def safe_thread_wrapper(func, current_ctx, *args, **kwargs):
    """
    Safely executes a function in a separate thread while preserving Streamlit's
    ScriptRunContext. This ensures thread-bound session_state and UI renders
    don't throw missing context exceptions.
    """
    import threading
    from streamlit.runtime.scriptrunner import add_script_run_ctx
    if current_ctx:
        add_script_run_ctx(threading.current_thread(), current_ctx)
    return func(*args, **kwargs)

from contextlib import asynccontextmanager

@asynccontextmanager
async def manage_download_lock(filepath):
    # get_running_loop() is the correct API from Python 3.7+ when called
    # from within a running coroutine (get_event_loop() is deprecated for this).
    current_loop = asyncio.get_running_loop()
    current_loop_id = id(current_loop)

    # Push threading.Lock acquisitions to the executor so they never block
    # the event loop thread if contended under high concurrency (H-16).
    def _acquire_slot():
        with _lock_mutex_local:
            entry = _download_locks.get(filepath)
            if entry is None or entry.get("loop_id") != current_loop_id:
                # Fresh entry or stale lock from a dead event loop - new Lock.
                _download_locks[filepath] = {"lock": asyncio.Lock(), "count": 0, "loop_id": current_loop_id}
            _download_locks[filepath]["count"] += 1
            return _download_locks[filepath]["lock"]

    def _release_slot():
        with _lock_mutex_local:
            entry = _download_locks.get(filepath)
            if entry:
                entry["count"] -= 1
                # <= 0, not == 0: when a run on a NEW event loop replaces a
                # stale entry (the branch above), the previous loop's holders
                # still release against the replacement and drive its count
                # negative. An exact-zero test then never fires and the entry
                # is pinned in the dict for the life of the process, once per
                # distinct file path.
                if entry["count"] <= 0:
                    _download_locks.pop(filepath, None)

    file_lock = await current_loop.run_in_executor(None, _acquire_slot)
    try:
        async with file_lock:
            yield
    finally:
        await current_loop.run_in_executor(None, _release_slot)

# --- Constants ---
MAX_RETRIES = 5
RETRY_DELAY = 1

# Upper bound on a server-supplied Retry-After, in seconds. `Retry-After` is a
# number chosen by the other end, and it was being obeyed literally: a header of
# 86400 parked the run on a one-second cancel-polling loop for a DAY, looking
# for all the world like a hang. Two minutes is far longer than any real Canvas
# throttle and still bounded; past that the retry budget runs out and the file
# is reported honestly instead of waiting in silence.
MAX_RETRY_AFTER_SECONDS = 120


def parse_retry_after(raw, fallback) -> int:
    """Whole seconds to wait from a ``Retry-After`` header, clamped to something
    sane.

    RFC 7231 also permits an HTTP-date, and a hostile or misconfigured proxy can
    send anything at all, so a value that is not a usable positive number falls
    back to the caller's own backoff. Returns an ``int`` because both call sites
    put the number in front of the user ("retry in 3s") and count it out one
    second at a time.
    """
    try:
        wait = int(raw)
    except (ValueError, TypeError):
        wait = 0
    if wait <= 0:
        try:
            return max(0, int(fallback))
        except (ValueError, TypeError):
            return RETRY_DELAY
    return min(wait, MAX_RETRY_AFTER_SECONDS)

# --- Secondary Content Configuration Defaults ---
# These are the settings that the UI will eventually expose as checkboxes.
# The backend operates on whatever dict it receives; defaults ensure safety.
SECONDARY_CONTENT_DEFAULTS = {
    'download_assignments': False,
    'download_syllabus': False,
    'download_announcements': False,
    'download_discussions': False,
    'download_quizzes': False,
    'download_rubrics': False,
    'download_submissions': False,
    'isolate_secondary_content': True,   # True = Mode B (subfolder), False = Mode A (inline)
}


def _extract_canvas_file_links(html_body):
    """Parse an HTML body and extract Canvas file download links.

    Instructors often embed file references as ``<a>`` tags inside
    assignment/announcement descriptions rather than using the Canvas
    ``attachments`` API field.  This function discovers those links.

    Returns
    -------
    list[dict]
        Each dict has ``'file_id'`` (int) and ``'link_text'`` (str).
        Deduplicated by ``file_id``.
    """
    if not html_body:
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_body, 'html.parser')
    except Exception:
        return []

    seen_ids = set()
    results = []

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if '/files/' not in href:
            continue

        # Extract file_id from patterns like:
        #   /courses/123/files/456/download
        #   /files/456/download?download_frd=1
        #   /courses/123/files/456?wrap=1
        try:
            # Split on '/files/' and take the segment after it
            after_files = href.split('/files/', 1)[1]
            # The file_id is the next path segment (digits)
            file_id_str = after_files.split('/')[0].split('?')[0]
            file_id = int(file_id_str)
        except (IndexError, ValueError):
            continue

        if file_id in seen_ids:
            continue
        seen_ids.add(file_id)

        link_text = a_tag.get_text(strip=True) or f'file_{file_id}'
        results.append({'file_id': file_id, 'link_text': link_text})

    return results


# A student is never allowed to read a quiz's questions, and Canvas says so with
# 403 Forbidden. `Forbidden` is a SIBLING of `Unauthorized` under
# `CanvasException`, not a subclass - so `except (Unauthorized, ...)` never
# caught the one case it was written for, and every student fell through to the
# generic handler. Measured on quiz 107362: `Forbidden {"status":"unauthorized",
# ...}`. The payload says "unauthorized"; the class does not.
_QUIZ_DENIED = (Forbidden, Unauthorized, ResourceDoesNotExist)

_QUIZ_QUESTIONS_DENIED_HTML = (
    '<p><em>Quiz questions could not be downloaded. Canvas only serves them '
    'to teachers, so this happens for every student-visible quiz - it does '
    'not mean the quiz is empty. Open it in Canvas to take or review '
    'it.</em></p>'
)


def _quiz_questions_html(quiz, debug_file=None) -> str:
    """The quiz's questions as HTML, or an honest statement of why not.

    ONE implementation, because the alternative was measured: the bulk quiz
    path fetched questions, the module-item quiz path and every assignment path
    did not, and a quiz that arrived through one of those was saved with an
    empty body. `_save_secondary_entity` then rendered the generic placeholder,
    so the file read "(No content provided)" - which is the wrong statement
    about a quiz whose questions exist and which Canvas simply will not serve
    to a student. Course 43660 produced both files for the same quiz: the
    Quizzes/ copy explained itself, the Assignments/ copy said it was empty.
    """
    # THE ITERATION MUST BE INSIDE THE TRY. `get_questions()` returns a
    # canvasapi PaginatedList, which is LAZY: it touches the network on the
    # first `next()`, not on the call. Guarding only the call catches nothing
    # and the Forbidden escapes into the caller - which is what happened the
    # first time this was refactored, and only the live API showed it, because
    # a test double raises eagerly.
    out = []
    try:
        for num, q in enumerate(quiz.get_questions(), start=1):
            q_name = getattr(q, 'question_name', f'Question {num}')
            q_text = getattr(q, 'question_text', '') or ''
            q_type = getattr(q, 'question_type', 'unknown')
            block = (
                f'<div style="margin:15px 0;padding:10px;'
                f'border:1px solid #ddd;border-radius:5px;">'
                f'<h3>Q{num}: {html.escape(q_name)}</h3>'
                f'<p style="color:#666;font-size:0.85em;">'
                f'Type: {html.escape(q_type)}</p>'
                f'{q_text}'
                f'</div>'
            )
            answers = getattr(q, 'answers', None)
            if answers and isinstance(answers, list):
                items = ''.join(
                    f'<li>{a.get("text", "") or a.get("html", "") or ""}</li>'
                    for a in answers)
                block += f'<ul>{items}</ul>'
            out.append(block)
    except _QUIZ_DENIED:
        return _QUIZ_QUESTIONS_DENIED_HTML
    except Exception as e:
        log_debug(f"Could not fetch questions for quiz "
                  f"{getattr(quiz, 'id', '?')}: {e}", debug_file)
        return ('<p><em>Quiz questions could not be loaded. '
                'Open the quiz in Canvas to see them.</em></p>')
    return ''.join(out)


def quiz_body_html(quiz, debug_file=None) -> str:
    """A quiz's saved body: its description, then its questions section."""
    body = getattr(quiz, 'description', '') or ''
    questions = _quiz_questions_html(quiz, debug_file)
    if questions:
        body += '<h2>Questions</h2>' + questions
    return body


def quiz_id_of_assignment(assignment):
    """The quiz behind an assignment, when the assignment IS a quiz.

    Canvas exposes an online quiz TWICE - as a quiz and as its shadow
    assignment - and a module can hold either. Reached through the assignment,
    `description` is empty by nature, because for a quiz the content IS the
    questions. Measured on assignment 32347: ``submission_types
    ['online_quiz']``, ``is_quiz_assignment True``, ``quiz_id 107362``,
    ``description ''``.
    """
    if not getattr(assignment, 'is_quiz_assignment', False) and \
            'online_quiz' not in (getattr(assignment, 'submission_types', []) or []):
        return None
    return getattr(assignment, 'quiz_id', None)


def resolve_discussion_topic(course, content_id, debug_file=None):
    """A module item's discussion topic, by whichever endpoint answers.

    Canvas can LIST a topic and then refuse the individual GET for it.
    Measured on course 43660, topic 166950 ("Spørgsmål til pensum i
    organisationskultur"): ``get_discussion_topics()`` returns it complete,
    with its message body - and ``get_discussion_topic(166950)`` raises
    ``ResourceDoesNotExist: Not Found``. It is not a group discussion, it is
    not locked, and it is visible in the browser.

    The module path only ever tried the individual GET, so the whole item
    failed: no file written for a discussion the user can plainly read, and a
    "Discussion Dispatch Error" on the completion screen that names something
    the user cannot act on. Falling back to the collection is the same
    "prefer the richer object, keep the other as fallback" shape the assignment
    path already uses - in the other direction.
    """
    try:
        return course.get_discussion_topic(content_id)
    except Exception as e:
        try:
            for t in course.get_discussion_topics():
                if getattr(t, 'id', None) == content_id:
                    log_debug(f"Discussion {content_id} is not available "
                              f"individually ({e}); using the copy from the "
                              f"topic list instead.", debug_file)
                    return t
        except Exception as le:
            log_debug(f"Discussion {content_id}: individual fetch failed "
                      f"({e}) and the topic list also failed ({le})", debug_file)
        raise


def assignment_body_html(course, assignment, description, debug_file=None) -> str:
    """An assignment's saved body - including its questions when it IS a quiz.

    An online quiz's assignment description is empty by nature, because for a
    quiz the content is the questions. Saving that empty string made
    ``_save_secondary_entity`` render "(No content provided)", which says the
    teacher left it blank - about a quiz that has questions Canvas simply will
    not serve to a student. The app already knew better: the same quiz saved
    through the quizzes path, two folders away, explained itself correctly.
    """
    quiz_id = quiz_id_of_assignment(assignment)
    if not quiz_id:
        return description
    try:
        quiz = course.get_quiz(quiz_id)
    except Exception as e:
        log_debug(f"Assignment {getattr(assignment, 'id', '?')} is quiz "
                  f"{quiz_id} but it could not be fetched: {e}", debug_file)
        return description or _QUIZ_QUESTIONS_DENIED_HTML
    body = description or (getattr(quiz, 'description', '') or '')
    questions = _quiz_questions_html(quiz, debug_file)
    if questions:
        body += '<h2>Questions</h2>' + questions
    return body


# Maps entity types to their subfolder names (Mode B) and prefixes (Mode A)
_ENTITY_ROUTING = {
    'assignment':   {'folder': 'Assignments',   'prefix': 'Assignment'},
    'syllabus':     {'folder': 'Syllabus',      'prefix': 'Syllabus'},
    'announcement': {'folder': 'Announcements', 'prefix': 'Announcement'},
    'discussion':   {'folder': 'Discussions',   'prefix': 'Discussion'},
    'quiz':         {'folder': 'Quizzes',       'prefix': 'Quiz'},
    'rubric':       {'folder': 'Rubrics',       'prefix': 'Rubric'},
    # "Submission Feedback", not "Submissions": the app deliberately does NOT
    # download the student's own uploaded files (they already have those on the
    # machine they submitted from). What this entity carries is the FEEDBACK on a
    # submission - grade, rubric assessment, teacher comments, and any files the
    # teacher attached to a comment. A folder called "Submissions" would promise
    # the opposite of what is inside it.
    'submission':   {'folder': 'Submission Feedback', 'prefix': 'Feedback'},
    'page':         {'folder': 'Pages',         'prefix': 'Page'},
    'link':         {'folder': 'Links',         'prefix': 'Link'},
}

def compute_entity_content_sig(entity_type: str, obj) -> str:
    """Content signature for a fetched secondary entity (H-1 update detection).

    THE single source of truth for which raw Canvas-side fields define an
    entity's content. The SAME function runs on both sides of the pipeline:

      - analysis (``get_secondary_content_metadata``) computes the fresh sig
        that ``_is_canvas_newer`` compares against the manifest, and
      - the save path (``_save_secondary_entity`` callers) stamps the sig
        into the manifest after writing the file,

    so a mismatch can only mean the source content actually changed. Fields
    are chosen to EXCLUDE anything locally rendered (HTML template, date
    formatting, 12h/24h preference) and anything Canvas churns without a
    content change (course-level ``updated_at``, grade events):

      assignment   name, description, due_at, points, submission types
      quiz         title, description, points, due_at, time limit, attempts,
                   question_count (question edits usually change the count or
                   the description; per-question bodies are NOT fetched - too
                   expensive for analysis)
      discussion   title, message, last_reply_at, reply count
      announcement title, message, posted_at, last_reply_at, reply count
      syllabus     body only
      page         title + the page's own updated_at (bodies are not fetched
                   during analysis; page-level updated_at only moves on edits)
      link         title + target URL
      rubric       title + updated_at

    Returns '' when *obj* is None (unknown → the analyzer treats it as
    "cannot verify" and never flags an update from it).
    """
    if obj is None:
        return ''
    g = lambda attr: getattr(obj, attr, None)  # noqa: E731 - tiny local accessor
    if entity_type == 'assignment':
        return secondary_content_sig(
            'assignment', g('name'), g('description'), g('due_at'),
            g('points_possible'), ','.join(g('submission_types') or []),
        )
    if entity_type == 'quiz':
        return secondary_content_sig(
            'quiz', g('title'), g('description'), g('points_possible'),
            g('due_at'), g('time_limit'), g('allowed_attempts'),
            g('question_count'),
        )
    if entity_type == 'discussion':
        return secondary_content_sig(
            'discussion', g('title'), g('message'), g('last_reply_at'),
            g('discussion_subentry_count'),
        )
    if entity_type == 'announcement':
        return secondary_content_sig(
            'announcement', g('title'), g('message'), g('posted_at'),
            g('last_reply_at'), g('discussion_subentry_count'),
        )
    if entity_type == 'syllabus':
        # obj is the syllabus body string itself (callers pass it directly -
        # course-level updated_at churns on unrelated changes and must never
        # participate in the signature).
        return secondary_content_sig('syllabus', obj)
    if entity_type == 'page':
        return secondary_content_sig('page', g('title'), g('updated_at'))
    if entity_type == 'rubric':
        return secondary_content_sig('rubric', g('title'), g('updated_at'))
    if entity_type == 'submission':
        # Feedback only. Deliberately EXCLUDES the student's own submission
        # fields (submitted_at, attempt, body, their attachments): re-submitting
        # must not present itself as "the teacher's feedback changed". What does
        # define this entity is the grade, when it was graded, the rubric
        # assessment, and the comment thread - so a new comment or a regrade
        # moves the signature and nothing else does.
        _comments = g('submission_comments') or []
        _rubric = g('rubric_assessment') or {}
        return secondary_content_sig(
            'submission',
            g('entered_grade') or g('grade'),
            g('entered_score') if g('entered_score') is not None else g('score'),
            g('graded_at'), g('workflow_state'),
            len(_comments),
            # comment identity AND text, so an edited comment is detected
            '|'.join(f"{_comment_field(c, 'id')}:{_comment_field(c, 'comment')}"
                     for c in _comments),
            # rubric criteria ratings, order-independent
            '|'.join(f"{k}:{(v or {}).get('points')}:{(v or {}).get('comments')}"
                     for k, v in sorted(_rubric.items())) if isinstance(_rubric, dict) else '',
        )
    return ''


def _comment_field(comment, field: str):
    """Read *field* off a submission comment, which Canvas returns as a dict but
    canvasapi may hand back as an object depending on the endpoint."""
    if isinstance(comment, dict):
        return comment.get(field, '')
    return getattr(comment, field, '')


def _submission_has_feedback(sub) -> bool:
    """True when a submission carries anything worth saving.

    A submission with no grade, no rubric assessment and no comments has no
    feedback in it - saving a file that says "not graded yet" for every
    assignment in the course would be noise. This is the same hide-until-relevant
    rule the Panopto summary uses.
    """
    if sub is None:
        return False
    g = lambda a: getattr(sub, a, None)  # noqa: E731
    if g('entered_grade') or g('grade'):
        return True
    if g('entered_score') is not None or g('score') is not None:
        return True
    if g('rubric_assessment'):
        return True
    for c in (g('submission_comments') or []):
        if str(_comment_field(c, 'comment') or '').strip():
            return True
    return False


def _submission_comment_attachments(sub) -> list:
    """Every file a teacher attached to a comment, as attachment dicts.

    Only COMMENT attachments. ``submission.attachments`` - the student's own
    uploaded files - is deliberately never returned: the app's standing decision
    is that the student already has what they handed in, and re-downloading it
    wastes bandwidth and clutters the folder. Teacher attachments are the
    opposite: an annotated PDF of your own essay usually exists nowhere else.
    """
    out, seen = [], set()
    for c in (getattr(sub, 'submission_comments', None) or []):
        atts = _comment_field(c, 'attachments') or []
        if not isinstance(atts, list):
            continue
        for a in atts:
            if not isinstance(a, dict):
                a = {k: getattr(a, k, None) for k in
                     ('id', 'url', 'filename', 'display_name', 'size',
                      'updated_at', 'content-type', 'content_type')}
            aid, url = a.get('id'), a.get('url')
            if not aid or not url or aid in seen:
                continue
            seen.add(aid)
            out.append({
                'id': aid,
                'url': url,
                'filename': a.get('filename') or a.get('display_name') or f"attachment-{aid}",
                'display_name': a.get('display_name') or a.get('filename') or f"attachment-{aid}",
                'size': a.get('size', 0) or 0,
                'modified_at': a.get('updated_at', '') or '',
                'content-type': a.get('content-type') or a.get('content_type') or '',
            })
    return out


def _submission_entity_id(sub):
    """The assignment id a submission's feedback is filed under, or ``None``.

    Returns None rather than falling back to 0. Fabricating 0 is actively
    harmful: ``make_secondary_id('submission', 0)`` is the SAME value for every
    id-less submission, so two of them would collide onto one manifest row and
    one feedback file would overwrite the other - and 0 lands exactly on a
    synthetic-id range boundary.

    The sync enumerator (``get_secondary_content_metadata``) and the downloader
    (``_fetch_and_save_submissions``) must both use this. If one included a
    submission the other skipped, sync would list a file that never arrives and
    re-list it on every run.
    """
    a = getattr(sub, 'assignment', None)
    if isinstance(a, dict):
        inlined = a.get('id')
    elif a is not None:
        inlined = getattr(a, 'id', None)
    else:
        inlined = None
    for candidate in (getattr(sub, 'assignment_id', None), inlined):
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value:
            return abs(value)
    return None


def link_content_sig(title: str, url: str) -> str:
    """Signature for an ExternalUrl/ExternalTool shortcut: a changed target
    URL (or renamed link) re-syncs the .url/.webloc file."""
    return secondary_content_sig('link', title, url)


def _apply_page_stub_upgrades(slug_groups, stub_results, module_map, sanitize) -> int:
    """Upgrade module-Page entries to the download engine's -page_id identity.

    ``slug_groups`` maps a page slug to its queued fixups - tuples of
    ``(entry, slug, legacy_item_id, module_name)`` where *entry* is the
    CanvasFileInfo that was emitted with the module-item FALLBACK id because
    the Pages LIST endpoint (page_meta) was restricted. ``stub_results`` is
    the per-slug fetch outcome: ``(slug, page_stub | None)``.

    For every successful fetch the entry is mutated in place to match what the
    download engine records in the manifest: ``id = -page_id`` with the
    module-item id preserved as ``legacy_sync_id``, filename/display re-derived
    from the page's own title (the downloader names the file after it), the
    page content signature computed, and the page id registered in
    *module_map* for path routing. A failed fetch leaves its entries on the
    module-item id (the pre-existing degraded behaviour). Returns the number
    of entries upgraded.
    """
    fixed = 0
    for _slug, _pg in stub_results:
        _pgid = int(getattr(_pg, 'page_id', 0) or 0) if _pg is not None else 0
        if not _pgid:
            continue
        for _mi, _slug_key, _legacy_id, _mname in slug_groups.get(_slug, []):
            _mi.id = -_pgid
            _mi.legacy_sync_id = _legacy_id
            _pg_title = getattr(_pg, 'title', None)
            if _pg_title:
                _safe = sanitize(_pg_title)
                _routing = _ENTITY_ROUTING['page']
                _mi.filename = f"{_routing['prefix']}: {_safe}.html"
                _mi.display_name = _safe + ".html"
                _mi._page_title = _pg_title
            try:
                _mi.content_sig = compute_entity_content_sig('page', _pg)
            except Exception:
                pass
            _pg_updated = getattr(_pg, 'updated_at', '') or ''
            if _pg_updated:
                _mi.modified_at = _pg_updated
            module_map.setdefault(-_pgid, _mname)
            fixed += 1
    return fixed


# Feature flag: rubric fetching is temporarily disabled.
# The Canvas course-level rubrics endpoint (GET /courses/:id/rubrics) requires
# the teacher/admin `manage_rubrics` permission, so student tokens always get a
# 401 - the feature could never work for the typical user and only produced
# noisy "user not authorised" errors. All rubric handling code is intentionally
# kept intact; flip this back to True to fully re-enable rubric download (both
# the metadata-listing path used by sync analysis AND the secondary-content
# download path used by Download mode are gated on this single flag).
RUBRICS_ENABLED = False

# Re-enabling rubrics takes MORE than flipping the flag above. There are two
# independent gates, and this one is the easy half:
#
#   1. This flag (checked in the metadata enumerator and the download path).
#   2. `persistent_dl_rubrics`, which is READ at four sites (app.py:886 and :1213,
#      sync/analysis.py:141, sync/execution.py:787) and WRITTEN NOWHERE - because
#      'dl_rubrics' was removed from SECONDARY_CONTENT_KEYS (core/state_registry.py)
#      and from the Card 2 toggle list (ui/download_settings.py). Every one of
#      those reads therefore returns its False default, so `download_rubrics` is
#      False in every composed settings dict regardless of this flag.
#
# So a full re-enable is: flip this flag, restore 'dl_rubrics' to
# SECONDARY_CONTENT_KEYS, and restore the Card 2 toggle (its icon is still
# shipped as assets/icon_rubrics.png, deliberately kept for exactly this).


# Guards for humanize_canvas_error's payload parsing. A Canvas error body is a
# few hundred bytes; anything vastly larger is an HTML error page or a truncated
# stream, never something with a 'message' worth extracting.
_ERR_PAYLOAD_MAX_CHARS = 64_000
_ERR_PAYLOAD_MAX_DEPTH = 40

#: Deepest reply nesting rendered into a discussion's HTML export.
#:
#: Same rule as ``_ERR_PAYLOAD_MAX_DEPTH`` above and as the folder walk in
#: ``panopto.discovery._discover_folder_sessions`` (depth <= 3, <= 40 folders):
#: a recursive walk over SERVER-shaped data needs a bound of its own. Two things
#: made this one worth capping rather than trusting:
#:
#:   * ``entry.get_replies()`` is a NETWORK call, so the recursion costs one
#:     HTTP request per level per entry - unbounded work driven by the other
#:     end, the same shape as the pagination loops in panopto/discovery;
#:   * a reply graph that ever came back cyclic would recurse until
#:     RecursionError, which the enclosing ``except Exception`` swallows into
#:     an empty string - i.e. the whole Replies section silently vanishes from
#:     the export rather than failing loudly.
#:
#: 30 is far past anything real: Canvas's own UI nests a handful of levels, and
#: this renderer's indent already saturates at depth 5 (``min(depth*30, 150)``).
_DISCUSSION_MAX_REPLY_DEPTH = 30


def humanize_canvas_error(exc) -> str:
    """Turn a Canvas/canvasapi exception into text that is safe to show a user.

    canvasapi raises ``CanvasException`` subclasses whose ``message`` is the
    PARSED JSON error body, so ``str(exc)`` is a Python **repr** of a dict::

        {'errors': [{'message': 'Invalid access token.'}]}

    Rendering that verbatim leaked into the login screen for the single most
    common failure in the app's lifetime (an expired saved token). It is also
    actively harmful: the repr contains "invalid access token" but none of
    "invalid token" / "unauthorized" / "401", so the login screen's keyword
    routing fell through to its generic branch and printed the repr as
    "Technical Details".

    Returns the innermost human message(s), joined; falls back to ``str(exc)``
    when the payload is not a recognised Canvas error shape. Never raises.
    """
    raw = str(exc) if exc is not None else ''
    if not raw:
        return ''

    payload = getattr(exc, 'message', None)
    if not isinstance(payload, (dict, list, tuple)):
        # canvasapi stringifies the payload, so parse the repr back. literal_eval
        # (not json.loads) because a Python repr uses single quotes. The leading
        # '(' matters: plain CanvasException wraps its body in a TUPLE, as in
        # ("Something went wrong. ", {'message': ...}).
        #
        # Size cap + bare `except Exception`: this runs INSIDE except blocks all
        # over the engine, so it must honour its "never raises" contract
        # absolutely - raising here would replace the real error with a confusing
        # one. literal_eval cannot execute code, but it CAN hit RecursionError on
        # a deeply nested payload (not covered by ValueError/SyntaxError), and it
        # is pointlessly slow on a megabyte of HTML.
        if raw.startswith(('{', '[', '(')) and len(raw) <= _ERR_PAYLOAD_MAX_CHARS:
            try:
                import ast as _ast
                payload = _ast.literal_eval(raw)
            except Exception:
                payload = None
        else:
            payload = None

    def _messages(node, depth: int = 0) -> list[str]:
        """Depth-first collect of every 'message' string in a nested payload.

        Depth-capped for the same reason as the parse above - an adversarial or
        merely odd payload must not be able to raise RecursionError out of an
        exception handler.
        """
        found: list[str] = []
        if depth > _ERR_PAYLOAD_MAX_DEPTH:
            return found
        if isinstance(node, dict):
            for key, val in node.items():
                if key == 'message' and isinstance(val, str) and val.strip():
                    found.append(val.strip())
                else:
                    found.extend(_messages(val, depth + 1))
        elif isinstance(node, (list, tuple)):
            for item in node:
                found.extend(_messages(item, depth + 1))
        elif isinstance(node, str) and node.strip():
            found.append(node.strip())
        return found

    if payload is not None:
        msgs, seen = [], set()
        for m in _messages(payload):
            low = m.lower()
            if low not in seen:
                seen.add(low)
                msgs.append(m)
        if msgs:
            return ' '.join(msgs)

    return raw


def _format_canvas_date(date_str):
    """
    Formats ISO 8601 UTC strings from Canvas (e.g., '2025-08-26T14:07:50Z')
    into human-readable localized strings like '26th August, 2025 at 14:07'.
    When 12-hour format is enabled, uses American ordering: 'August 26th, 2025 at 2:07 PM'.
    """
    if not date_str or not isinstance(date_str, str):
        return str(date_str)
    try:
        # Convert Canvas Zulu time 'Z' to explicit UTC '+00:00' for Python parsing
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        # Astimezone inherently converts to the user's local operating system timezone
        local_dt = dt.astimezone()
        
        # Calculate English ordinal suffix for the day
        day = local_dt.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["st", "nd", "rd"][day % 10 - 1]
            
        # Format time component respecting 12h/24h preference
        try:
            import streamlit as st
            use_12h = st.session_state.get('use_12h_format', False)
        except Exception:
            use_12h = False

        if use_12h:
            time_fmt = local_dt.strftime('%I:%M %p').lstrip('0')
            # American: "August 26th, 2025 at 2:07 PM"
            return f"{local_dt.strftime('%B')} {day}{suffix}, {local_dt.year} at {time_fmt}"
        else:
            time_fmt = local_dt.strftime('%H:%M')
            # European: "26th August, 2025 at 14:07"
            return f"{day}{suffix} {local_dt.strftime('%B')}, {local_dt.year} at {time_fmt}"
    except Exception:
        return date_str

def _build_rubric_markdown(rubric) -> str:
    """Serialise a Canvas rubric into a Markdown table.

    Shared by the initial-download path (_fetch_and_save_rubrics) and the
    sync path (download_secondary_entity) so both produce IDENTICAL .md
    content. Previously the sync path wrapped its body in the full HTML
    document template, corrupting the .md file on every rubric update.
    """
    r_title = getattr(rubric, 'title', 'Untitled Rubric')
    r_description = getattr(rubric, 'description', '') or ''
    criteria = getattr(rubric, 'data', None) or []

    md_content = f"# Rubric: {r_title}\n\n"

    r_html_url = getattr(rubric, 'html_url', None)
    if r_html_url:
        md_content += f"[View on Canvas]({r_html_url})\n\n"

    if r_description:
        md_content += f"{r_description}\n\n"

    if criteria:
        # Build table header from first criterion's ratings.
        # `or 0` guards against points being present-but-None, which would
        # crash sorted() with a None<int comparison and abort the rubric.
        sample_ratings = criteria[0].get('ratings', [])
        headers = ['Criterion'] + [
            f"{r.get('description', '?')} ({r.get('points', '?')})"
            for r in sorted(sample_ratings,
                            key=lambda x: x.get('points') or 0,
                            reverse=True)
        ]
        md_content += '| ' + ' | '.join(headers) + ' |\n'
        md_content += '|' + '---|' * len(headers) + '\n'

        for criterion in criteria:
            row = [criterion.get('description', '')]
            c_ratings = sorted(
                criterion.get('ratings', []),
                key=lambda x: x.get('points') or 0,
                reverse=True,
            )
            for rating in c_ratings:
                long_desc = rating.get('long_description', '')
                short_desc = rating.get('description', '')
                row.append(long_desc or short_desc)
            # Pad row if ratings count differs
            while len(row) < len(headers):
                row.append('')
            md_content += '| ' + ' | '.join(row) + ' |\n'
    else:
        md_content += '*No criteria data available.*\n'

    return md_content


def is_auth_error(exc) -> bool:
    """Return True if *exc* is an authentication/authorization failure (expired or
    revoked Canvas token), centralizing the scattered 401 / "unauthorized" checks.

    Matches:
      - canvasapi ``Unauthorized``
      - any exception whose ``status_code`` is 401
      - any exception whose message mentions 401 / unauthorized / "user not authorised"

    Deliberately does NOT match 403/Forbidden (a permission issue on a valid
    token) - those are not "reconnect your account" situations.
    """
    if exc is None:
        return False
    if isinstance(exc, Unauthorized):
        return True
    if getattr(exc, 'status_code', None) == 401:
        return True
    msg = str(exc).lower()
    return ('401' in msg
            or 'unauthorized' in msg
            or 'user not authorised' in msg
            or 'invalid access token' in msg
            or 'expired' in msg)


class DownloadError:
    """Structured error object for UI display and logging."""
    def __init__(self, course_name, item_name, error_type, message, raw_error=None, context=None, is_app_error=False):
        self.course_name = course_name
        self.item_name = item_name
        self.error_type = error_type # e.g., '401', 'Rate Limit', 'Network', 'Generic'
        self.message = message
        self.raw_error = str(raw_error) if isinstance(raw_error, Exception) else raw_error
        self.context = context or {}
        self.is_app_error = is_app_error  # True for engine/infra failures, not individual file failures
        # True once this file has been through an isolated retry and still failed.
        # Re-categorizes the error from "Failed to Download" (retriable) to
        # "Cannot Be Downloaded" (permanent) on the completion screen.
        self.retry_exhausted = False
        self.timestamp = datetime.now(timezone.utc)

    def __str__(self):
        return f"[{self.course_name}] {self.message}"

    def to_log_entry(self):
        """Format for log file"""
        ts = self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        return f"[{ts}] [{self.course_name}] [{self.error_type}] {self.item_name}: {self.message}"

# Vanity-URL resolution is a blocking HTTPS round-trip to the institution's
# Canvas root, and it runs in CanvasManager.__init__ - so every construction
# paid for it. The completion screens build one manager PER COURSE (twice over,
# once for the error-log paths and once for the folder paths) purely to reach
# _sanitize_filename, which turned the download -> complete transition into a
# second of blocking I/O while Streamlit streamed the screen in element by
# element. The answer for a given input URL never changes inside a session, so
# resolve it once and remember it.
_RESOLVED_CANVAS_URLS: dict[str, str] = {}
_RESOLVED_CANVAS_URLS_LOCK = threading.Lock()


def _is_canonical_canvas_host(api_url: str) -> bool:
    """True when the URL is already the instructure.com host resolution looks for.

    The resolver's entire job is to follow a vanity domain to its
    ``*.instructure.com`` target, so a URL that IS one has nothing to resolve -
    the round-trip can only ever return the address it was given. Skipping it
    saves a full page fetch of the Canvas landing page (measured 0.70s on a good
    connection, and it sits on the startup path before anything is on screen;
    on a slow link it runs to the 5s timeout).
    """
    try:
        host = urllib.parse.urlparse(api_url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    return host == "instructure.com" or host.endswith(".instructure.com")


def real_canvas_file_id(file_obj) -> int | None:
    """The real Canvas **file** id behind a download task, or None if there is none.

    A single Canvas file reaches the engine through several phases under
    different ids: the Files tab and the module walk use its true positive id,
    while an announcement / assignment / quiz / discussion / submission
    attachment is re-keyed to a synthetic negative id in isolate mode. Asking
    ``file_obj.id`` therefore cannot tell you that two tasks are the same file -
    which is exactly how one file came to be fetched twice, 21 seconds apart
    (course 46396, ids 1784620 and 1807289).

    Only the ``attachment`` synthetic band maps back to a file id. Every other
    band holds an ENTITY id from a different namespace, so a quiz id of 1784620
    must never match the file of the same number - hence the explicit gate
    rather than a bare :func:`secondary_raw_id`.
    """
    try:
        fid = int(getattr(file_obj, 'id', 0) or 0)
    except (TypeError, ValueError):
        return None
    if fid > 0:
        return fid
    if fid < 0 and secondary_id_type(fid) == 'attachment':
        return secondary_raw_id(fid)
    return None


# Module items that are not FILES: a Canvas Page exports to .html, an
# ExternalUrl/ExternalTool to a .webloc (macOS) / .url (Windows) shortcut.
LINK_LIKE_MODULE_ITEM_TYPES = ('Page', 'ExternalUrl', 'ExternalTool')


def module_item_in_scope(item_type: str, file_filter: str) -> bool:
    """Would a download with *file_filter* produce anything for this module item?

    ONE definition, because it was written in four places and the fourth
    disagreed. The download engine skips Pages and links outright under the
    "Slides & PDFs" filter (`file_filter == 'study'`) - three `if file_filter ==
    'study': continue` sites in `download_course_async` - while
    `get_course_files_metadata`, which feeds the sync ANALYZER, enumerated them
    unconditionally.

    The consequence was permanent, not cosmetic. Measured on a real folder
    (course 43660, flat + study): the manifest holds 0 rows for .html/.webloc
    because the download never produced them, so the analyzer reported
    **76 new files on every sync, for ever** - 35 Pages plus every module link -
    and accepting them would have quietly turned the folder into a shape the user
    never configured. The user's own words: "seventy six files have not been added
    to the course since I downloaded it right before".

    Out of scope is NOT the same as ignored: `is_ignored` means the user decided
    to skip something, and these were never offered to them. They are simply
    outside what this folder is for, so they are dropped before the diff rather
    than listed anywhere.
    """
    if item_type in LINK_LIKE_MODULE_ITEM_TYPES:
        return file_filter != 'study'
    return True


# The "Slides & PDFs" filter's allowlist. ONE definition: this list was written
# out by hand in FOUR places (the download gate, the two estimators, and Quick
# Sync's own re-filter), which is the same divergent-primitive shape as
# `make_long_path`'s duplicate in core/sync_manager.py and the three AppleScript
# escapers - a rule written more than once is a rule some caller is following an
# old version of.
STUDY_FILE_EXTENSIONS = frozenset({'.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx'})


def file_in_scope(disk_name, file_filter: str) -> bool:
    """Would a download with *file_filter* keep this Files-tab file?

    The companion of `module_item_in_scope` for the other half of a course: that
    one answers for module ITEMS by type, this one for FILES by extension. Both
    exist because the download engine and the sync analyzer have to agree on what
    a folder is for, and where they disagreed the analyzer offered files the
    engine would never have produced - permanently, on every sync.

    **Pass the name the file will have ON DISK, not `file_obj.filename`.** Canvas
    exposes two names per file and the engine writes `preferred_disk_name`, which
    prefers the teacher-curated `display_name`; the two can carry different
    extensions ("Lecture" vs "Lecture.pdf"). The estimators used to read the raw
    `filename` here, so a course could be counted one way and downloaded another.
    A path is accepted as well as a bare name - `analyze_course` holds the
    computed destination, which is the most authoritative form of all.

    **The name is URL-unquoted first, because `_sanitize_filename` does that too**
    and the two must reach the same verdict. Canvas serves URL-encoded filenames
    routinely (see the `'Klyngevejledning+-+Upload.pptx'` note in
    sync/execution.py), and the engine asks this question about the SANITIZED name
    while the analyzer and the estimators ask it about the raw one. Measured:
    `Lecture%2Epdf` sanitizes to `Lecture.pdf`, so the engine downloads it while an
    un-unquoted check saw no extension at all and dropped it - the silent-missing-
    file direction, which is worse than the bug this predicate exists to fix.
    Unquoting here rather than at the six call sites is what makes them agree by
    construction. None of the sanitizer's other steps can change a short extension
    (its length truncation only cuts one longer than 10 characters).
    """
    if file_filter != 'study':
        return True
    name = str(disk_name)
    try:
        name = urllib.parse.unquote_plus(name)
    except Exception:
        pass
    return PurePath(name).suffix.lower() in STUDY_FILE_EXTENSIONS


class CanvasManager:
    def __init__(self, api_key, api_url):
        self.api_key = api_key
        # Clean and validate URL
        api_url = api_url.strip()
        if not api_url:
            self.api_url = "" # Let validation fail later
        else:
            if not api_url.startswith("http"):
                api_url = "https://" + api_url

            # --- Auto-Resolve Vanity URLs (memoised - see above) ---
            _url_before_resolve = api_url
            with _RESOLVED_CANVAS_URLS_LOCK:
                _cached = _RESOLVED_CANVAS_URLS.get(_url_before_resolve)
            if _cached is not None:
                api_url = _cached
            elif _is_canonical_canvas_host(api_url):
                with _RESOLVED_CANVAS_URLS_LOCK:
                    _RESOLVED_CANVAS_URLS[_url_before_resolve] = api_url
            else:
                try:
                    import requests
                    # Attempt to follow redirects to find the true Canvas domain (e.g. .instructure.com).
                    # Match on the HOSTNAME, never a substring: an SSO redirect whose URL merely
                    # CONTAINS "instructure.com" (typically in a ?return=/?url= query param pointing
                    # back at the Canvas host) would otherwise hijack resolution onto the SSO host and
                    # every API call would then hit a login portal. Prefer the final destination; fall
                    # back to the first genuinely-canonical hop in the redirect chain.
                    res = requests.get(api_url, timeout=5)
                    if _is_canonical_canvas_host(res.url):
                        api_url = res.url
                    else:
                        for r in res.history:
                            if _is_canonical_canvas_host(r.url):
                                api_url = r.url
                                break
                except Exception:
                    # Not cached: a resolution that failed because the network
                    # was down must be retried, not remembered as "no redirect".
                    pass
                else:
                    with _RESOLVED_CANVAS_URLS_LOCK:
                        _RESOLVED_CANVAS_URLS[_url_before_resolve] = api_url

            from urllib.parse import urlparse
            try:
                parsed = urlparse(api_url)
                # Reconstruct URL retaining strictly scheme and netloc
                self.api_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            except Exception:
                self.api_url = api_url.rstrip("/")
            
        # Initialize Canvas object
        try:
            self.canvas = self._new_canvas_client(self.api_url, self.api_key)
        except Exception:
            # If URL is completely malformed, Canvas init might fail immediately
            self.canvas = None
            
        self.user = None
        self._logged_error_sigs = set()  # Dedup cache: prevents same error being logged twice in one run
        self.error_log_enabled = False    # Toggled via Settings; when False, download_errors.txt is not created

    def __repr__(self):
        """Redacted repr - never expose the Canvas Access Token in tracebacks or log output."""
        return f"CanvasManager(api_url={self.api_url!r}, api_key='****')"

    @staticmethod
    def _new_canvas_client(api_url, api_key):
        """Build a canvasapi ``Canvas`` with the shared request-timeout adapter mounted.

        Each ``Canvas`` owns its own ``requests.Session``.  A dedicated client is
        required whenever a Canvas call must run **concurrently** with another one
        (a ``requests.Session`` is not guaranteed safe for concurrent use) - e.g.
        the parallel page-metadata fetch in ``get_course_files_metadata``.  The
        timeout adapter makes slow calls raise ``Timeout`` instead of hanging
        forever on cross-continent connections.
        """
        canvas = Canvas(api_url, api_key)
        try:
            _adapter = _CanvasTimeoutAdapter()
            canvas._Canvas__requester._session.mount('https://', _adapter)
            canvas._Canvas__requester._session.mount('http://', _adapter)
        except Exception as _e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"Could not mount timeout adapter on canvasapi session: {_e}. "
                "API calls will have no timeout and may hang on slow connections."
            )
        return canvas

    def validate_token(self):
        """Checks if the token is valid by attempting to fetch the current user.

        Returns ``(ok, message)``. On failure the message is always
        human-readable - never a raw Python repr (see humanize_canvas_error).
        Auth failures are normalised so the login UI's keyword routing can
        recognise them: canvasapi's own text is "Invalid access token.", which
        matches none of the obvious keywords.

        The normalised text deliberately avoids the word "expired". The login
        screen routes an EXPIRED token to its own "Token Expired" notice by
        matching that word, and `is_auth_error` matches it too - so listing it
        here as one of several possibilities would make every revoked or deleted
        token report itself as expired. Canvas says "expired" when it means it;
        this wording covers only what the exception actually proves.
        """
        if not self.api_url or not self.canvas:
            return False, 'Login failed. Please check that your Canvas URL and Canvas Access Token are correct.'

        try:
            # We attempt to fetch the user. This validates both the URL and Token.
            self.user = self.canvas.get_current_user()
            return True, f'Logged in as: {self.user.name}'
        except Unauthorized as e:
            # The single most common failure over the app's lifetime: the saved
            # token is no longer accepted. Lead with a phrase the UI matches, and
            # let Canvas's own text (appended in the parentheses) be the thing
            # that says "expired" when that is genuinely the cause.
            return False, (
                'Unauthorized - your Canvas Access Token is not valid or '
                f'has been revoked. ({humanize_canvas_error(e)})'
            )
        except Exception as e:
            msg = humanize_canvas_error(e)
            return False, msg or ('Login failed. Please check that your Canvas URL '
                                  'and Canvas Access Token are correct.')

    def get_courses(self, favorites_only=True):
        """
        Fetches courses. 
        Raises exceptions for UI to handle (no silent failures).
        """
        if not self.canvas:
             raise ValueError("Canvas object not initialized (check URL).")

        if favorites_only:
            # Lazy-load user if not already set
            if self.user is None:
                self.user = self.canvas.get_current_user()
            courses = self.user.get_favorite_courses()
        else:
            # Fetch ALL enrollments - deliberately unfiltered. The previous
            # enrollment_state=['active', 'invited_or_pending'] filter hid
            # past-semester courses on Canvas instances that conclude
            # enrollments at term end, breaking the "archive last semester"
            # use case. Courses the student can no longer open come back as
            # access-restricted stubs WITHOUT a 'name' attribute and are
            # dropped by the hasattr filter below.
            courses = self.canvas.get_courses()
        
        # Validation/Filter loop (might raise API errors if connection drops)
        course_list = []
        for course in courses:
            if hasattr(course, 'name') and hasattr(course, 'id'):
                    course_list.append(course)
        return course_list

    def get_courses_with_favorites(self):
        """Every enrolled course, each annotated ``.is_favorite``, in ONE request.

        The obvious implementation - fetch all courses, then fetch the favorites
        and intersect - costs **three** sequential Canvas round-trips, because
        ``canvasapi``'s ``get_current_user()`` eagerly does ``GET /users/self``
        before it will hand over ``get_favorite_courses()``. Measured against a
        real instance 2026-07-31: 950 ms for ``/courses`` (309 ms) +
        ``/users/self`` (253 ms) + ``/users/self/favorites/courses`` (298 ms).

        Canvas can answer the whole question in one call: ``include[]=favorites``
        adds ``is_favorite`` to every course in the list. Same instance, same
        moment: **432 ms, one request**, and the set of courses it flags matched
        the favorites endpoint exactly (15 of 33, identical ids).

        Unknown ``include[]`` values are IGNORED by Canvas rather than rejected,
        so an instance that does not support it returns courses with no
        ``is_favorite`` attribute at all - which is why the result is *verified*
        rather than assumed, and why the three-call path is still here as the
        fallback rather than deleted.
        """
        if not self.canvas:
            raise ValueError("Canvas object not initialized (check URL).")

        courses = [c for c in self.canvas.get_courses(include=['favorites'])
                   if hasattr(c, 'name') and hasattr(c, 'id')]
        if courses and all(hasattr(c, 'is_favorite') for c in courses):
            for c in courses:
                c.is_favorite = bool(c.is_favorite)
            return courses

        # This instance did not honour include[]=favorites (or there are no
        # courses at all, in which case both paths agree and this is free).
        if courses:
            logger.info("Canvas ignored include[]=favorites; using the "
                        "favorites endpoint instead (one extra round-trip).")
        fav_ids = set()
        try:
            fav_ids = {c.id for c in self.get_courses(favorites_only=True)}
        except Exception as e:
            logger.warning(f"favorites fetch failed, treating all as non-favorite: {e}")
        for c in courses:
            c.is_favorite = c.id in fav_ids
        return courses

    def get_course_files_metadata(self, course, progress_callback=None, secondary_content_settings=None,
                                  is_scanning_phase=False, timings=None, download_mode=None,
                                  file_filter='all'):
        """
        Fetch metadata for all files in a course using a robust Hybrid strategy.
        
        Strategy:
        1. Try to fetch all files using `course.get_files()`. This is the primary source.
           - If it fails mid-stream, we CATCH the error but KEEP the files found so far.
        2. Always run a secondary scan of Modules to find files that might be locked/hidden 
           or were missed due to the error in step 1.
        3. Deduplicate by File ID.
        4. Optionally merge metadata for secondary content entities (Assignments, etc.).
        
        ``timings`` (dict | None): when provided, populated in place with the
        per-phase wall-clock in ms - ``bulk_files_ms``, ``pages_ms``,
        ``fetch_parallel_ms`` (wall-clock of the overlapped bulk‖pages block),
        ``module_scan_ms`` and ``secondary_ms`` - for the analysis debug log.

        Returns:
            Tuple of (list[CanvasFileInfo], dict, dict):
              - List of CanvasFileInfo objects (unique by ID)
              - Secondary fetch success status dict
              - Module map: content_id (int) → sanitized module folder name (str)
        """
        from core.sync_manager import CanvasFileInfo
        import time

        all_files_map = {} # ID -> CanvasFileInfo
        module_map = {}  # content_id (int) -> sanitized module folder name (str)

        # ── Phase 1 (bulk files) ‖ Page metadata ──────────────────────────────
        # These two Canvas fetches are mutually independent (the module scan needs
        # BOTH before it can run), so off the scanning path we overlap them in two
        # threads.  The bulk fetch keeps using this manager's shared session; the
        # page fetch runs on a FRESH Canvas client (its own requests.Session) so
        # the two never touch the same session concurrently.  Neither branch calls
        # st.* / progress_callback, so no ScriptRunContext is needed on the workers.

        def _fetch_bulk_files():
            """Phase 1: bulk ``course.get_files()`` → {id: CanvasFileInfo}.
            Swallows access/pagination errors and keeps whatever it gathered so
            the module scan can supplement any gaps."""
            _map = {}
            try:
                # We iterate manually to catch errors during pagination
                for file in course.get_files():
                    if not getattr(file, 'url', ''):
                        logger.debug(f"Skipping locked/restricted file: {getattr(file, 'filename', '<unknown>')} in course {getattr(course, 'name', '?')}")
                        continue
                    try:
                        _map[file.id] = CanvasFileInfo(
                            id=file.id,
                            filename=getattr(file, 'filename', ''),
                            display_name=getattr(file, 'display_name', getattr(file, 'filename', '')),
                            size=getattr(file, 'size', 0),
                            modified_at=getattr(file, 'modified_at', None),
                            md5=getattr(file, 'md5', None),
                            url=getattr(file, 'url', ''),
                            content_type=getattr(file, 'content-type', ''),
                            folder_id=getattr(file, 'folder_id', None),
                        )
                    except Exception as e:
                        logger.warning(f"Error parsing file object {getattr(file, 'id', '?')}: {e}")
            except (Unauthorized, ResourceDoesNotExist, CanvasException):
                logger.debug(f"Files tab not accessible for course {getattr(course, 'id', '?')} (permission denied - module scan will supplement)")
                # Expected for courses with restricted Files tabs; Phase 2 module scan recovers the files.
            except Exception as e:
                logger.warning(f"Error during get_course_files_metadata bulk fetch: {e}")
                # We do NOT raise here. We continue to Phase 2 to supplement what we found.
            return _map

        def _fetch_page_meta():
            """Page CONTENT signatures require each page's own updated_at + title,
            which module items don't carry and per-page fetches would make N+1.
            One ``course.get_pages()`` list call yields stubs with page_url, title
            and updated_at for every page - enough to sign without bodies.  Runs on
            a fresh Canvas client so it is safe to overlap the bulk fetch.
            Returns {page_slug: page_stub}."""
            _meta = {}
            try:
                _client = self._new_canvas_client(self.api_url, self.api_key)
                _course = _client.get_course(course.id)
                for _pg in _course.get_pages():
                    _slug = getattr(_pg, 'url', '') or ''
                    if _slug:
                        _meta[_slug] = _pg
            except (Unauthorized, ResourceDoesNotExist, CanvasException):
                logger.debug(f"Pages list not accessible for course {getattr(course, 'id', '?')}")
            except Exception as e:
                logger.debug(f"Page metadata fetch failed: {e}")
            return _meta

        def _timed(fn):
            _s = time.perf_counter()
            _r = fn()
            return _r, int((time.perf_counter() - _s) * 1000)

        page_meta: dict = {}
        _fetch_start = time.perf_counter()
        if is_scanning_phase:
            # Scanning phase never fetches pages - run the bulk fetch inline.
            all_files_map, _bulk_ms = _timed(_fetch_bulk_files)
            _pages_ms = 0
        else:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="canvas-meta") as _ex:
                _fut_files = _ex.submit(_timed, _fetch_bulk_files)
                _fut_pages = _ex.submit(_timed, _fetch_page_meta)
                all_files_map, _bulk_ms = _fut_files.result()
                page_meta, _pages_ms = _fut_pages.result()
        if timings is not None:
            timings['bulk_files_ms'] = _bulk_ms
            timings['pages_ms'] = _pages_ms
            timings['fetch_parallel_ms'] = int((time.perf_counter() - _fetch_start) * 1000)

        # --- Phase 2: Module Scan (Supplement) ---
        _module_scan_start = time.perf_counter()
        try:
            # Pass the IDs already gathered by the bulk fetch so the module
            # scan can skip its per-item course.get_file() call for files we
            # already have metadata for - eliminating an N+1 API pattern on
            # every sync analysis / scanning pass (the module_map entry is
            # still recorded for path routing).
            module_files, module_map = self._get_files_from_modules(course, progress_callback=progress_callback,
                                                                    secondary_content_settings=secondary_content_settings,
                                                                    known_file_ids=set(all_files_map.keys()),
                                                                    page_meta=page_meta,
                                                                    download_mode=download_mode,
                                                                    file_filter=file_filter)
            module_only_count = 0
            for f_info in module_files:
                if f_info.id not in all_files_map:
                    all_files_map[f_info.id] = f_info
                    module_only_count += 1
            
            # Diagnostic: If bulk fetch missed items that modules found, it suggests Files tab is restricted/hidden
            if module_only_count > 0:
                logger.warning(
                    f"Hybrid Fetch: Found {module_only_count} files in Modules that were missing from 'Files' tab. "
                    f"This suggests 'Files' tab access is restricted for course {course.id}."
                )
                    
        except Exception as e:
            logger.error(f"Error during module scan fallback: {e}")
            if progress_callback:
                progress_callback(f"Module scan failed - some files may be missing: {e}", progress_type='log')
        if timings is not None:
            timings['module_scan_ms'] = int((time.perf_counter() - _module_scan_start) * 1000)

        # --- Phase 3: Secondary Content Metadata ---
        # Pass the module map so attachments of module-linked entities can
        # inherit their parent's module folder (Mode A path routing).
        _secondary_start = time.perf_counter()
        secondary_fetch_success = {}
        if secondary_content_settings:
            try:
                secondary_items, secondary_fetch_success = self.get_secondary_content_metadata(
                    course, secondary_content_settings,
                    is_scanning_phase=is_scanning_phase,
                    module_map=module_map,
                )
                for s_info in secondary_items:
                    # Phase-3 items are AUTHORITATIVE for secondary entities:
                    # they carry the full bodies and therefore the content
                    # signatures update detection depends on, while the
                    # module-scan stubs (Phase 2) have neither. Overwrite -
                    # the module_map placement entries recorded in Phase 2
                    # live in a separate dict and are unaffected.
                    all_files_map[s_info.id] = s_info
            except Exception as e:
                logger.error(f"Error fetching secondary content metadata: {e}")
                if progress_callback:
                    progress_callback(f"Canvas Content scan failed - some items may be missing: {e}", progress_type='log')
        if timings is not None:
            timings['secondary_ms'] = int((time.perf_counter() - _secondary_start) * 1000)

        return list(all_files_map.values()), secondary_fetch_success, module_map

    def _get_files_from_modules(self, course, progress_callback=None, secondary_content_settings=None,
                                known_file_ids=None, page_meta=None, download_mode=None,
                                file_filter='all'):
        """Fallback: Get files by iterating through modules.

        ``known_file_ids`` (set[int] | None): file IDs already fetched by the
        bulk ``get_files()`` pass. Module items matching these IDs skip the
        per-item ``course.get_file()`` HTTP call (their module_map entry is
        still recorded), avoiding an N+1 request pattern on large courses. Any
        remaining File items (common when the Files tab is restricted, so the
        bulk pass returned nothing) are resolved AFTER the module walk with a
        parallel ``get_file()`` fan-out - each worker on its own Canvas session.

        ``page_meta`` ({page_url_slug: page_stub} | None): page stubs from a
        single course.get_pages() call, used to compute Page content
        signatures (title + the page's own updated_at) without per-page
        fetches. None/missing slugs simply leave the signature empty.

        Also emits mock CanvasFileInfo for secondary entity types
        (Assignment, Quiz, Discussion, Page, ExternalUrl) when
        *secondary_content_settings* enables them.  This allows the sync
        analysis engine to see these entities without additional API calls.

        ``module_map`` is keyed by **both** raw positive Canvas file IDs
        (for ordinary File items) **and** synthetic negative IDs (for
        secondary content), so ``analyze_course`` can resolve a module
        subfolder for every entity that lives inside a module - which is
        what lets Mode A inline secondary content land in the right
        module subfolder during sync.

        Returns:
            Tuple of (list[CanvasFileInfo], dict):
              - List of discovered file info objects
              - Module map: ID (int, positive or synthetic-negative) →
                sanitized module folder name (str)
        """
        from core.sync_manager import CanvasFileInfo

        # Determine secondary-content layout mode once. Mode A (isolate=False)
        # needs filenames carrying the routing prefix so the analyzer's
        # calc_path = "<module>/Type: Foo.html" matches the on-disk layout.
        # Mode B (isolate=True) keeps basenames; _resolve_secondary_path
        # handles the actual category/folder placement at write time.
        isolate = True
        if secondary_content_settings:
            isolate = secondary_content_settings.get('isolate_secondary_content', True)

        files = []
        module_map = {}
        # content_id → first-linking module name, for File items whose metadata
        # the bulk get_files() pass didn't already provide.  Collected during the
        # module walk and resolved in parallel AFTER it (see below): on a course
        # with a restricted Files tab EVERY module File item needs its own
        # get_file(), and doing those serially is by far the dominant cost of the
        # whole analysis.  Keyed by content_id so a file linked from several
        # modules is fetched only once (first-linking module wins, matching
        # module_map and the download engine).
        pending_file_fetches: dict = {}
        # Page module items whose stub was NOT in page_meta. course.get_pages()
        # (the pages LIST endpoint) 401s on courses whose Pages tab is hidden -
        # the same restriction class as the Files tab above - even though every
        # individual page remains fetchable BY SLUG (which is exactly how the
        # download engine gets its page_id). Without the stub these items fall
        # back to the module-item id, breaking id-parity with the manifest and
        # re-flagging every downloaded page as "new" (the 2026-07-09
        # 35-phantom-new bug). Collected during the walk, fetched by slug in
        # parallel AFTER it, and upgraded in place.
        pending_page_fixups: list = []
        try:
            modules = list(course.get_modules())
        except Exception as e:
            logger.warning(f"Could not fetch module list for course {getattr(course, 'id', '?')}: {e}")
            if progress_callback:
                progress_callback(f"Could not fetch modules: {e}", progress_type='log')
            return files, module_map
        total_modules = len(modules)

        # Per-worker Canvas client (its own requests.Session) so the parallel
        # fetches below never touch a shared session. Built lazily once per
        # worker thread and cached; reused by BOTH the module-items fan-out here
        # and the per-file metadata fan-out further down.
        import concurrent.futures as _cf
        import threading as _threading
        from canvasapi.module import Module as _CanvasModule
        _tls = _threading.local()

        def _worker_course():
            _c = getattr(_tls, 'course', None)
            if _c is None:
                _c = self._new_canvas_client(self.api_url, self.api_key).get_course(course.id)
                _tls.course = _c
            return _c

        # ── Fetch every module's item list in parallel ───────────────────────
        # One HTTP call per module; done serially this is the dominant remaining
        # cost on many-module courses. The Module is built straight from the
        # worker's requester (no extra get_module round trip). ``_ex.map``
        # preserves input order, so first-linking-module-wins is unchanged.
        def _fetch_module_items(module):
            _name = self._sanitize_filename(getattr(module, 'name', 'Module'))
            try:
                _m = _CanvasModule(_worker_course()._requester,
                                   {'id': module.id, 'course_id': course.id})
                return _name, list(_m.get_module_items())
            except Exception as e:
                logger.warning(f"Could not fetch items for module '{getattr(module, 'name', '?')}': {e}")
                return _name, None

        if modules:
            _items_workers = min(8, len(modules))
            with _cf.ThreadPoolExecutor(max_workers=_items_workers,
                                        thread_name_prefix="canvas-moditems") as _ex:
                _modules_items = list(_ex.map(_fetch_module_items, modules))
        else:
            _modules_items = []

        for idx, (clean_module_name, items) in enumerate(_modules_items):
            if progress_callback:
                progress_callback(idx + 1, total_modules, f"Scanning module: {clean_module_name}")
            if items is None:
                continue
            for item in items:
                if item.type == 'File':
                    if not hasattr(item, 'content_id') or not item.content_id:
                        continue
                    # M-5: FIRST linking module wins (matches the download
                    # engine, which saves one physical copy into the first
                    # module that links the file).
                    module_map.setdefault(item.content_id, clean_module_name)
                    if known_file_ids and item.content_id in known_file_ids:
                        # Already in the bulk get_files() result - the
                        # module_map entry above is all this item needed.
                        continue
                    # Defer the per-file get_file() HTTP call; resolved in
                    # parallel after the module walk (first-linking module wins).
                    pending_file_fetches.setdefault(item.content_id, clean_module_name)
                elif item.type in LINK_LIKE_MODULE_ITEM_TYPES:
                    # Out of scope for this folder's filter -> not a candidate at
                    # all. Enumerating them here is what made the analyzer report
                    # them as new for ever; see module_item_in_scope.
                    if not module_item_in_scope(item.type, file_filter):
                        continue
                    try:
                        # M-1 parity: Pages and links are MODULE ITEMS, written
                        # by the download engine into the module folder with the
                        # "Page: " prefix for pages, REGARDLESS of the secondary
                        # content isolate mode. The analyzer must expect the
                        # exact same shape, or every already-downloaded page
                        # looks "new" and freshly-synced ones land at the root.
                        #
                        # ...with ONE exception, added 2026-07-29: in FLAT mode
                        # there is no module folder to keep the page in, so
                        # "module placement" degenerates to the course root and
                        # the isolate setting is the only instruction left. See
                        # `_page_isolated` below.
                        ext = ".html" if item.type == 'Page' else (".webloc" if platform.system() == 'Darwin' else ".url")

                        _sig = ''
                        _page_stub = None
                        if item.type == 'Page' and page_meta:
                            _page_stub = page_meta.get(getattr(item, 'page_url', '') or '')

                        # Prefer the page's OWN title (what the downloader
                        # names the file after) over the module item title.
                        _title = (getattr(_page_stub, 'title', None)
                                  or getattr(item, 'title', 'Untitled'))
                        safe_base = self._sanitize_filename(_title)
                        # A module Page goes to its category folder only when the
                        # user asked to isolate AND there is no module folder for
                        # it to live in - i.e. flat mode. In modules mode the page
                        # stays with its module, which is the layout that mode is
                        # for. The folder is carried IN THE NAME because the
                        # analyzer's flat-mode `target_paths` is empty by design
                        # (sync_manager.analyze_course only fills it for modules
                        # mode), and `preferred_disk_name` passes a name_locked
                        # negative-id name through verbatim - so this is the one
                        # place that can state the expected path at all.
                        _page_isolated = (item.type == 'Page' and isolate
                                          and download_mode == 'flat')
                        if item.type == 'Page':
                            routing = _ENTITY_ROUTING['page']
                            if _page_isolated:
                                emitted_filename = f"{routing['folder']}/{safe_base}{ext}"
                            else:
                                emitted_filename = f"{routing['prefix']}: {safe_base}{ext}"
                            if _page_stub is not None:
                                _sig = compute_entity_content_sig('page', _page_stub)
                        else:
                            emitted_filename = safe_base + ext

                        actual_url = getattr(item, 'html_url', None) or getattr(item, 'external_url', None) or getattr(item, 'url', '')
                        if item.type != 'Page':
                            # Link signature: a renamed link or changed target
                            # URL re-syncs the .url/.webloc shortcut.
                            #
                            # It MUST be computed from `actual_url` - the very
                            # string written into the shortcut below (url=... on
                            # the CanvasFileInfo) - and not from a separately
                            # derived one. The two orderings differ:
                            #
                            #   actual_url : html_url  or external_url or url
                            #   the old sig: external_url or html_url
                            #
                            # For an ExternalUrl item they coincide (Canvas
                            # leaves html_url empty), which is why this went
                            # unnoticed. For an ExternalTool item they NEVER do:
                            # html_url is the Canvas module-item URL that lands
                            # in the file, while external_url is the shared LTI
                            # launch endpoint - literally the same string for
                            # every recording in the course. So the signature
                            # described a URL the file did not contain, could
                            # not match the one recorded at download time, and
                            # every Panopto shortcut was offered as a "clean
                            # update" on every analysis, for ever. Measured on
                            # 43660: 36 phantom updates on a folder downloaded
                            # minutes earlier, with 0 md5 mismatches.
                            #
                            # Same family as the Pages identity bug documented
                            # just below - download and scan must agree on what
                            # identifies an entity.
                            #
                            # ONLY ExternalTool changes. Measured on 43660, both
                            # directions, by comparing the stored signature
                            # against one recomputed from the URL actually
                            # inside each shortcut:
                            #
                            #   ExternalUrl  file holds external_url, stored sig
                            #                is sig(external_url) -> the original
                            #                ordering is already right, and
                            #                switching it to html_url turned 5
                            #                correct rows into phantom updates.
                            #   ExternalTool file holds html_url, stored sig is
                            #                sig(html_url) -> external_url is the
                            #                shared LTI launch endpoint, the same
                            #                string for all 36 recordings, so it
                            #                can never identify one.
                            _link_url = (
                                (getattr(item, 'html_url', None)
                                 or getattr(item, 'external_url', None) or '')
                                if item.type == 'ExternalTool' else
                                (getattr(item, 'external_url', None)
                                 or getattr(item, 'html_url', '') or '')
                            )
                            _sig = link_content_sig(getattr(item, 'title', 'Untitled'),
                                                    _link_url)
                        # ID parity with the download engine: Pages are recorded
                        # in the manifest by PAGE id (-page_id) at download time,
                        # but this scan historically emitted the MODULE ITEM id
                        # (-item.id) - so a freshly-downloaded course re-analyzed
                        # for sync saw every module Page as "new" and pulled a
                        # duplicate copy (the 2026-07-09 "35 new files on a fresh
                        # download" bug). Emit the page id when the pages listing
                        # provided it, and carry the module-item id as a LEGACY
                        # alias so folders synced by older versions (tracked
                        # under -item.id) keep matching too.
                        _item_syn_id = -int(item.id) if hasattr(item, 'id') else 0
                        syn_id = _item_syn_id
                        _legacy_alias = 0
                        if item.type == 'Page' and _page_stub is not None:
                            _pgid = int(getattr(_page_stub, 'page_id', 0) or 0)
                            if _pgid:
                                syn_id = -_pgid
                                _legacy_alias = _item_syn_id
                        if syn_id and not _page_isolated:
                            # Register placement: these items live in their
                            # module folder in both isolate modes - EXCEPT an
                            # isolated page in flat mode, whose folder is already
                            # carried in the emitted name. Registering one here
                            # too would produce "<module>/Pages/X.html".
                            module_map.setdefault(syn_id, clean_module_name)
                        if _legacy_alias and not _page_isolated:
                            module_map.setdefault(_legacy_alias, clean_module_name)

                        mock_info = CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=safe_base + ext,
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=actual_url,
                            content_type="text/html" if item.type == 'Page' else "application/x-url",
                            content_sig=_sig,
                            name_locked=True,
                            legacy_sync_id=_legacy_alias,
                        )
                        if item.type == 'Page':
                            # Stash the page slug so the sync engine can fetch
                            # the REAL page body (offline HTML parity with the
                            # download engine) instead of writing a redirect
                            # stub that requires a Canvas login to be useful.
                            _slug = getattr(item, 'page_url', '') or ''
                            mock_info._page_slug = _slug
                            mock_info._page_title = _title
                            if _page_stub is None and _slug:
                                # Pages LIST was restricted/missing this slug -
                                # queue a per-slug stub fetch so the entry can
                                # be upgraded to its real -page_id (see the
                                # fixup pass after the module walk).
                                pending_page_fixups.append(
                                    (mock_info, _slug, _item_syn_id, clean_module_name)
                                )
                        files.append(mock_info)
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process {item.type} item "
                            f"'{getattr(item, 'title', '?')}' in module "
                            f"'{clean_module_name}': {_item_err}"
                        )

                # --- Secondary entities found in modules ---
                elif item.type == 'Assignment' and secondary_content_settings and secondary_content_settings.get('download_assignments'):
                    try:
                        safe_base = self._sanitize_filename(getattr(item, 'title', 'Untitled'))
                        content_id = getattr(item, 'content_id', 0) or 0
                        syn_id = make_secondary_id('assignment', content_id)
                        if not isolate:
                            # First linking module wins (M-5 parity).
                            module_map.setdefault(syn_id, clean_module_name)
                        if isolate:
                            emitted_filename = safe_base + '.html'
                        else:
                            routing = _ENTITY_ROUTING['assignment']
                            emitted_filename = f"{routing['prefix']}: {safe_base}.html"
                        files.append(CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=getattr(item, 'title', 'Untitled'),
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=getattr(item, 'html_url', ''),
                            content_type='text/html',
                        ))
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process Assignment item '{getattr(item, 'title', '?')}' "
                            f"in module '{clean_module_name}': {_item_err}"
                        )
                elif item.type == 'Quiz' and secondary_content_settings and secondary_content_settings.get('download_quizzes'):
                    try:
                        safe_base = self._sanitize_filename(getattr(item, 'title', 'Untitled'))
                        content_id = getattr(item, 'content_id', 0) or 0
                        syn_id = make_secondary_id('quiz', content_id)
                        if not isolate:
                            # First linking module wins (M-5 parity).
                            module_map.setdefault(syn_id, clean_module_name)
                        if isolate:
                            emitted_filename = safe_base + '.html'
                        else:
                            routing = _ENTITY_ROUTING['quiz']
                            emitted_filename = f"{routing['prefix']}: {safe_base}.html"
                        files.append(CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=getattr(item, 'title', 'Untitled'),
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=getattr(item, 'html_url', ''),
                            content_type='text/html',
                        ))
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process Quiz item '{getattr(item, 'title', '?')}' "
                            f"in module '{clean_module_name}': {_item_err}"
                        )
                elif item.type == 'Discussion' and secondary_content_settings and secondary_content_settings.get('download_discussions'):
                    try:
                        safe_base = self._sanitize_filename(getattr(item, 'title', 'Untitled'))
                        content_id = getattr(item, 'content_id', 0) or 0
                        syn_id = make_secondary_id('discussion', content_id)
                        if not isolate:
                            # First linking module wins (M-5 parity).
                            module_map.setdefault(syn_id, clean_module_name)
                        if isolate:
                            emitted_filename = safe_base + '.html'
                        else:
                            routing = _ENTITY_ROUTING['discussion']
                            emitted_filename = f"{routing['prefix']}: {safe_base}.html"
                        files.append(CanvasFileInfo(
                            id=syn_id,
                            filename=emitted_filename,
                            display_name=getattr(item, 'title', 'Untitled'),
                            size=0,
                            modified_at=getattr(item, 'updated_at', datetime.now(timezone.utc).isoformat()),
                            url=getattr(item, 'html_url', ''),
                            content_type='text/html',
                        ))
                    except Exception as _item_err:
                        logger.warning(
                            f"Could not process Discussion item '{getattr(item, 'title', '?')}' "
                            f"in module '{clean_module_name}': {_item_err}"
                        )

        # ── Page-stub fallback: fetch missing page stubs BY SLUG in parallel ──
        # Fires only when page_meta lacked a Page item's slug (restricted Pages
        # LIST). The per-slug endpoint works regardless of tab visibility - it
        # is the same call the download engine uses - so the real page_id,
        # title and content signature are recovered and the emitted entry is
        # upgraded in place: id becomes -page_id (manifest parity with the
        # download engine) and the module-item id is kept as the legacy alias.
        # A failed fetch keeps the legacy module-item id (previous behaviour).
        if pending_page_fixups:
            _slug_groups: dict = {}
            for _entry in pending_page_fixups:
                _slug_groups.setdefault(_entry[1], []).append(_entry)

            def _fetch_page_stub(slug):
                try:
                    return slug, _worker_course().get_page(slug)
                except Exception as _pg_err:
                    logger.debug(f"Page stub fetch failed for slug '{slug}': {_pg_err}")
                    return slug, None

            with _cf.ThreadPoolExecutor(max_workers=min(8, len(_slug_groups)),
                                        thread_name_prefix="canvas-pagestub") as _pex:
                _stub_results = list(_pex.map(_fetch_page_stub, _slug_groups.keys()))

            _fixed_pages = _apply_page_stub_upgrades(
                _slug_groups, _stub_results, module_map, self._sanitize_filename
            )
            if _fixed_pages:
                logger.info(
                    f"Page-stub fallback: resolved {_fixed_pages} module Page item(s) "
                    f"by slug (Pages list restricted for course {getattr(course, 'id', '?')})"
                )

        # ── Resolve deferred per-file metadata fetches in parallel ────────────
        # This is the hot path for restricted-Files-tab courses (bulk get_files()
        # returns nothing, so every module File item lands here).  Each worker
        # uses its OWN Canvas client (fresh requests.Session via a thread-local)
        # so no session is touched concurrently; the workers never call st.* /
        # progress_callback (that stays on this thread, driven by as_completed).
        if pending_file_fetches:
            # Reuses the module-scan's per-worker Canvas client (_worker_course)
            # and _cf imported above.
            def _resolve_module_file(content_id, module_name):
                """Fetch one module-linked file's metadata on a worker thread.
                Returns a CanvasFileInfo, or None to skip (locked / no url /
                fetch failed).  A failure is logged and swallowed so one bad file
                never aborts the rest of the scan (the old serial path let a fetch
                error propagate and drop every remaining file)."""
                try:
                    _f = _worker_course().get_file(content_id)
                    if not getattr(_f, 'url', ''):
                        return None
                    return CanvasFileInfo(
                        id=_f.id,
                        filename=getattr(_f, 'filename', ''),
                        display_name=getattr(_f, 'display_name', getattr(_f, 'filename', '')),
                        size=getattr(_f, 'size', 0),
                        modified_at=getattr(_f, 'modified_at', None),
                        md5=getattr(_f, 'md5', None),
                        url=getattr(_f, 'url', ''),
                        content_type=getattr(_f, 'content-type', ''),
                        folder_id=getattr(_f, 'folder_id', None),
                    )
                except Exception as _fetch_err:
                    logger.warning(
                        f"Could not fetch file {content_id} from module "
                        f"'{module_name}': {_fetch_err}"
                    )
                    return None

            _total_pending = len(pending_file_fetches)
            _max_workers = min(8, _total_pending)
            _done = 0
            # Throttle progress pushes: the analysis progress hook does a ~50ms
            # DOM-flush sleep per call, so firing it once per file would re-add
            # seconds of latency that the parallel fetch just removed. Cap it to
            # ~20 updates across the whole batch (plus the final one).
            _progress_step = max(1, _total_pending // 20)
            with _cf.ThreadPoolExecutor(max_workers=_max_workers,
                                        thread_name_prefix="canvas-modfile") as _ex:
                _futs = [
                    _ex.submit(_resolve_module_file, _cid, _mname)
                    for _cid, _mname in pending_file_fetches.items()
                ]
                for _fut in _cf.as_completed(_futs):
                    _done += 1
                    _r = _fut.result()
                    if _r is not None:
                        files.append(_r)
                    # 3-positional form only - the analysis/scanning progress hooks
                    # don't accept progress_type kwargs.
                    if progress_callback and (_done % _progress_step == 0 or _done == _total_pending):
                        progress_callback(_done, _total_pending,
                                          f"Fetching file details ({_done}/{_total_pending})…")

        return files, module_map

    def get_secondary_content_metadata(self, course, settings, is_scanning_phase=False,
                                       module_map=None):
        """Return (items, fetch_success) for *standalone* secondary content.

        This covers entities that are NOT linked from any module and thus
        would not be surfaced by ``_get_files_from_modules``.  Examples:
        Announcements, Syllabus, standalone Assignments, Rubrics.

        Used by the sync analysis path to detect new/updated/missing
        secondary entities in the manifest.

        ``module_map`` is mutated in place: when an emitted attachment
        belongs to a module-linked parent entity (Assignment / Quiz /
        Discussion that already appears in ``module_map``), the
        attachment's ID is added so the analyzer can route Mode A
        attachments back into the correct module subfolder.

        Returns
        -------
        tuple[list[CanvasFileInfo], dict[str, bool]]
            ``(items, fetch_success)`` where ``fetch_success`` maps entity
            type strings to True/False indicating whether the API call
            succeeded.  The sync engine uses this to guard against false
            deletions when a fetch times out.
        """
        from core.sync_manager import CanvasFileInfo

        if module_map is None:
            module_map = {}

        items = []
        fetch_success = {}

        # Syllabus
        if settings.get('download_syllabus'):
            try:
                full_course = self.canvas.get_course(
                    course.id, include=['syllabus_body'],
                )
                if getattr(full_course, 'syllabus_body', None):
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['syllabus']
                    if isolate:
                        syl_filename = f"{routing['folder']}/Syllabus.html"
                    else:
                        syl_filename = f"{routing['prefix']}: Syllabus.html"
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('syllabus', course.id),
                        filename=syl_filename,
                        display_name='Syllabus',
                        size=0,
                        modified_at=getattr(full_course, 'updated_at', ''),
                        url='',
                        content_type='text/html',
                        content_sig=compute_entity_content_sig(
                            'syllabus', getattr(full_course, 'syllabus_body', '') or ''),
                        name_locked=True,
                    ))
                fetch_success['syllabus'] = True
            except Exception as e:
                logger.warning(f"Fetching syllabus failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['syllabus'] = False

        # Announcements
        if settings.get('download_announcements'):
            try:
                topics = course.get_discussion_topics(only_announcements=True)
                for topic in topics:
                    t_id = getattr(topic, 'id', 0)
                    title = getattr(topic, 'title', 'Announcement')
                    posted_at = getattr(topic, 'posted_at', '') or ''
                    
                    # Date-prefix for chronological file ordering (Alignment fix)
                    date_prefix = ''
                    if posted_at:
                        try:
                            dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
                            date_prefix = dt.strftime('%Y-%m-%d') + ' - '
                        except (ValueError, TypeError):
                            pass
                            
                    display_name = f"{date_prefix}{title}"
                    safe_title = self._sanitize_filename(display_name)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['announcement']
                    
                    attachments = []
                    try:
                        raw_att = getattr(topic, 'attachments', None)
                        if raw_att and isinstance(raw_att, list):
                            attachments = list(raw_att)
                    except Exception:
                        pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        t_msg = getattr(topic, 'message', '') or ''
                        for link_info in _extract_canvas_file_links(t_msg):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass

                    has_attachments = bool(attachments)
                    
                    if isolate:
                        if has_attachments:
                            ann_filename = f"{routing['folder']}/{safe_title}/{safe_title}.html"
                        else:
                            ann_filename = f"{routing['folder']}/{safe_title}.html"
                    else:
                        ann_filename = f"{routing['prefix']}: {safe_title}.html"
                        
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('announcement', t_id),
                        filename=ann_filename,
                        display_name=title,
                        size=0,
                        modified_at=getattr(topic, 'posted_at', ''),
                        url=getattr(topic, 'html_url', ''),
                        content_type='text/html',
                        content_sig=compute_entity_content_sig('announcement', topic),
                        name_locked=True,
                    ))
                    
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        att_raw_name = att.get('filename', att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_title}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            # Mode A: prefix attachment with parent entity's
                            # routing prefix so it matches the on-disk layout
                            # produced by _fetch_and_save_assignments / etc.
                            att_prefixed_name = f"{routing['prefix']}: {safe_title} - {att_raw_name}"

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name', att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', getattr(topic, 'posted_at', '')),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                            name_locked=True,
                        ))
                fetch_success['announcement'] = True
            except Exception as e:
                logger.warning(f"Fetching announcements failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['announcement'] = False

        # Standalone Assignments - fetch individually for timestamp parity
        # and attachment discovery (mirrors the download path exactly).
        if settings.get('download_assignments'):
            try:
                for assignment in course.get_assignments():
                    a_id = getattr(assignment, 'id', 0)
                    a_name = getattr(assignment, 'name', 'Assignment')
                    a_updated = getattr(assignment, 'updated_at', '') or ''

                    full_assignment = None
                    if not is_scanning_phase:
                        # Full sync analysis: fetch individually for
                        # timestamp parity and attachment discovery.
                        try:
                            full_assignment = course.get_assignment(a_id)
                        except Exception:
                            full_assignment = assignment
                        a_name = getattr(full_assignment, 'name', 'Assignment')
                        a_updated = getattr(full_assignment, 'updated_at', '') or ''

                    # --- Build the correct filename path ---
                    safe_name = self._sanitize_filename(a_name)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['assignment']

                    # Discover attachments (only in full analysis mode)
                    attachments = []
                    if full_assignment is not None:
                        try:
                            raw_att = getattr(full_assignment, 'attachments', None)
                            if raw_att and isinstance(raw_att, list):
                                attachments = list(raw_att)
                        except Exception:
                            pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        # Inline file links from the description HTML
                        a_desc = getattr(full_assignment, 'description', '') or ''
                        for link_info in _extract_canvas_file_links(a_desc):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename',
                                                        link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name',
                                                            link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass  # Inaccessible file - skip silently

                    has_attachments = bool(attachments)

                    # Build the filename to match _resolve_secondary_path
                    if isolate:
                        if has_attachments:
                            entity_filename = f"{routing['folder']}/{safe_name}/{safe_name}.html"
                        else:
                            entity_filename = f"{routing['folder']}/{safe_name}.html"
                    else:
                        entity_filename = f"{routing['prefix']}: {safe_name}.html"

                    # 1) The Assignment HTML entity itself (negative synthetic ID)
                    parent_syn_id = make_secondary_id('assignment', a_id)
                    items.append(CanvasFileInfo(
                        id=parent_syn_id,
                        filename=entity_filename,
                        display_name=a_name,
                        size=0,
                        modified_at=a_updated,
                        url=getattr(assignment, 'html_url', ''),
                        content_type='text/html',
                        content_sig=compute_entity_content_sig(
                            'assignment', full_assignment or assignment),
                        name_locked=True,
                    ))

                    # 2) Yield each attachment as a true CanvasFileInfo
                    parent_module = module_map.get(parent_syn_id, "")
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        # Unify namespace: prepend the parent entity's
                        # subfolder so the filename mirrors the physical
                        # extraction layout on disk.
                        att_raw_name = att.get('filename',
                                               att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_name}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            # Mode A: parent assignment writes attachments as
                            # "<prefix>: <a_name> - <filename>" alongside its
                            # HTML body (see _fetch_and_save_assignments).
                            att_prefixed_name = f"{routing['prefix']}: {safe_name} - {att_raw_name}"

                        # Inherit parent module placement so analyze_course
                        # can route Mode A attachments back into the parent
                        # assignment's module subfolder.
                        if parent_module:
                            module_map[att_id] = parent_module

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name',
                                                 att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', a_updated),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                            name_locked=True,
                        ))

                fetch_success['assignment'] = True
            except Exception as e:
                logger.warning(f"Fetching assignments failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['assignment'] = False

        # Standalone Discussions (non-announcement)
        if settings.get('download_discussions'):
            try:
                for topic in course.get_discussion_topics():
                    if getattr(topic, 'is_announcement', False):
                        continue
                    t_id = getattr(topic, 'id', 0)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['discussion']
                    d_title = getattr(topic, 'title', 'Discussion')
                    safe_title = self._sanitize_filename(d_title)
                    
                    attachments = []
                    try:
                        raw_att = getattr(topic, 'attachments', None)
                        if raw_att and isinstance(raw_att, list):
                            attachments = list(raw_att)
                    except Exception:
                        pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        t_msg = getattr(topic, 'message', '') or ''
                        for link_info in _extract_canvas_file_links(t_msg):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass

                    has_attachments = bool(attachments)
                    
                    if isolate:
                        if has_attachments:
                            disc_filename = f"{routing['folder']}/{safe_title}/{safe_title}.html"
                        else:
                            disc_filename = f"{routing['folder']}/{safe_title}.html"
                    else:
                        disc_filename = f"{routing['prefix']}: {safe_title}.html"
                        
                    parent_syn_id = make_secondary_id('discussion', t_id)
                    items.append(CanvasFileInfo(
                        id=parent_syn_id,
                        filename=disc_filename,
                        display_name=d_title,
                        size=0,
                        modified_at=getattr(topic, 'updated_at', ''),
                        url=getattr(topic, 'html_url', ''),
                        content_type='text/html',
                        content_sig=compute_entity_content_sig('discussion', topic),
                        name_locked=True,
                    ))

                    parent_module = module_map.get(parent_syn_id, "")
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        att_raw_name = att.get('filename', att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_title}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            att_prefixed_name = f"{routing['prefix']}: {safe_title} - {att_raw_name}"

                        if parent_module:
                            module_map[att_id] = parent_module

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name', att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', getattr(topic, 'updated_at', '')),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                            name_locked=True,
                        ))
                fetch_success['discussion'] = True
            except Exception as e:
                logger.warning(f"Fetching discussions failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['discussion'] = False

        # Quizzes
        if settings.get('download_quizzes'):
            try:
                for quiz in course.get_quizzes():
                    q_id = getattr(quiz, 'id', 0)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['quiz']
                    q_title = getattr(quiz, 'title', 'Quiz')
                    safe_title = self._sanitize_filename(q_title)
                    
                    attachments = []
                    try:
                        raw_att = getattr(quiz, 'attachments', None)
                        if raw_att and isinstance(raw_att, list):
                            attachments = list(raw_att)
                    except Exception:
                        pass

                    existing_att_ids = {
                        a.get('id') for a in attachments if isinstance(a, dict)
                    }

                    if not is_scanning_phase:
                        q_desc = getattr(quiz, 'description', '') or ''
                        for link_info in _extract_canvas_file_links(q_desc):
                            fid = link_info['file_id']
                            if fid in existing_att_ids:
                                continue
                            try:
                                canvas_file = course.get_file(fid)
                                attachments.append({
                                    'id': canvas_file.id,
                                    'url': canvas_file.url,
                                    'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                    'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                    'size': getattr(canvas_file, 'size', 0),
                                    'modified_at': getattr(canvas_file, 'modified_at', ''),
                                    'content-type': getattr(canvas_file, 'content_type', ''),
                                })
                                existing_att_ids.add(canvas_file.id)
                            except Exception:
                                pass

                    has_attachments = bool(attachments)
                    
                    if isolate:
                        if has_attachments:
                            quiz_filename = f"{routing['folder']}/{safe_title}/{safe_title}.html"
                        else:
                            quiz_filename = f"{routing['folder']}/{safe_title}.html"
                    else:
                        quiz_filename = f"{routing['prefix']}: {safe_title}.html"
                        
                    parent_syn_id = make_secondary_id('quiz', q_id)
                    items.append(CanvasFileInfo(
                        id=parent_syn_id,
                        filename=quiz_filename,
                        display_name=q_title,
                        size=0,
                        modified_at=getattr(quiz, 'updated_at', ''),
                        url=getattr(quiz, 'html_url', ''),
                        content_type='text/html',
                        content_sig=compute_entity_content_sig('quiz', quiz),
                        name_locked=True,
                    ))

                    parent_module = module_map.get(parent_syn_id, "")
                    for att in attachments:
                        raw_id = att.get('id')
                        if not raw_id:
                            continue
                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        att_raw_name = att.get('filename', att.get('display_name', 'attachment'))
                        if isolate and has_attachments:
                            att_prefixed_name = f"{routing['folder']}/{safe_title}/{att_raw_name}"
                        elif isolate:
                            att_prefixed_name = f"{routing['folder']}/{att_raw_name}"
                        else:
                            att_prefixed_name = f"{routing['prefix']}: {safe_title} - {att_raw_name}"

                        if parent_module:
                            module_map[att_id] = parent_module

                        items.append(CanvasFileInfo(
                            id=att_id,
                            filename=att_prefixed_name,
                            display_name=att.get('display_name', att.get('filename', 'attachment')),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', getattr(quiz, 'updated_at', '')),
                            url=att.get('url', ''),
                            content_type=att.get('content-type', ''),
                            name_locked=True,
                        ))
                fetch_success['quiz'] = True
            except (Unauthorized, ResourceDoesNotExist, CanvasException):
                logger.debug(f"Quizzes not accessible for course {getattr(course, 'id', '?')} (permission denied or not supported)")
                fetch_success['quiz'] = False
            except Exception as e:
                logger.warning(f"Fetching quizzes failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['quiz'] = False

        # Rubrics (temporarily disabled via RUBRICS_ENABLED - see flag definition)
        if RUBRICS_ENABLED and settings.get('download_rubrics'):
            try:
                for rubric in course.get_rubrics():
                    r_id = getattr(rubric, 'id', 0)
                    isolate = settings.get('isolate_secondary_content', True)
                    routing = _ENTITY_ROUTING['rubric']
                    r_title = getattr(rubric, 'title', 'Rubric')
                    safe_title = self._sanitize_filename(r_title)
                    if isolate:
                        rubric_filename = f"{routing['folder']}/{safe_title}.md"
                    else:
                        rubric_filename = f"{routing['prefix']}: {safe_title}.md"
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('rubric', r_id),
                        filename=rubric_filename,
                        display_name=r_title,
                        size=0,
                        modified_at=getattr(rubric, 'updated_at', ''),
                        url='',
                        content_type='text/markdown',
                        content_sig=compute_entity_content_sig('rubric', rubric),
                        name_locked=True,
                    ))
                fetch_success['rubric'] = True
            except (Unauthorized, ResourceDoesNotExist, CanvasException):
                logger.debug(f"Rubrics not accessible for course {getattr(course, 'id', '?')} (permission denied or not supported)")
                fetch_success['rubric'] = False
            except Exception as e:
                logger.warning(f"Fetching rubrics failed for course {getattr(course, 'id', '?')}: {e}")
                fetch_success['rubric'] = False

        # Submission feedback (grade + rubric + teacher comments). Enumerated here
        # so SYNC mode sees the same entities the download engine writes - the
        # analyzer keys off this list, so an entity missing here would be reported
        # as locally-deleted on every sync. Attachments on comments are real
        # Canvas files and are enumerated by the attachment path, not here.
        if settings.get('download_submissions'):
            try:
                isolate = settings.get('isolate_secondary_content', True)
                routing = _ENTITY_ROUTING['submission']
                for sub in self._fetch_submissions_with_feedback(course, None):
                    s_id = _submission_entity_id(sub)
                    if s_id is None:
                        continue    # unidentifiable - see _submission_entity_id
                    a_name = (self._submission_assignment_field(sub, 'name')
                              or f"Assignment {s_id}").strip()
                    safe_title = self._sanitize_filename(a_name)
                    has_attachments = bool(_submission_comment_attachments(sub))
                    if isolate:
                        if has_attachments:
                            sub_filename = f"{routing['folder']}/{safe_title}/{safe_title}.html"
                        else:
                            sub_filename = f"{routing['folder']}/{safe_title}.html"
                    else:
                        sub_filename = f"{routing['prefix']}: {safe_title}.html"
                    items.append(CanvasFileInfo(
                        id=make_secondary_id('submission', s_id),
                        filename=sub_filename,
                        display_name=a_name,
                        size=0,
                        modified_at=getattr(sub, 'graded_at', '') or '',
                        url=self._submission_assignment_field(sub, 'html_url') or '',
                        content_type='text/html',
                        content_sig=compute_entity_content_sig('submission', sub),
                        name_locked=True,
                    ))
                fetch_success['submission'] = True
            except (Unauthorized, ResourceDoesNotExist, CanvasException) as e:
                logger.debug(f"Submission feedback not accessible for course "
                             f"{getattr(course, 'id', '?')}: {humanize_canvas_error(e)}")
                fetch_success['submission'] = False
            except Exception as e:
                logger.warning(f"Fetching submission feedback failed for course "
                               f"{getattr(course, 'id', '?')}: {humanize_canvas_error(e)}")
                fetch_success['submission'] = False

        return items, fetch_success

    def get_folder_map(self, course) -> dict:
        """
        Fetch all folders in a course and return a mapping of folder_id to relative path.
        
        Returns:
            Dict mapping folder_id (int) to relative path string (e.g. 'Module 1/Sub').
            Returns empty dict on failure.
        """
        folder_map = {}
        try:
            all_folders = course.get_folders()
            for folder in all_folders:
                full_name = getattr(folder, 'full_name', '')
                if full_name.startswith("course files"):
                    rel_path = full_name[len("course files"):].strip('/')
                else:
                    rel_path = full_name
                folder_map[folder.id] = rel_path
        except Exception as e:
            logger.warning(f"Failed to fetch folder map for course: {e}")
        return folder_map


    def count_course_items(self, course, mode='modules', file_filter='all'):
        """
        Counts total number of downloadable items in a course.
        Matches the logic of download_course_async (including Hybrid Mode catch-all).
        """
        count = 0
        
        try:
            if mode == 'flat':
                # 1. Count Files
                try:
                    files = list(course.get_files())
                    for f in files:
                        if file_in_scope(preferred_disk_name(f), file_filter):
                            count += 1
                except Exception:
                    pass # Fallback to modules will catch files if get_files failed
                
                # 2. Count non-file Module Items 
                if file_filter != 'study':
                    try:
                        modules = course.get_modules()
                        for module in modules:
                            items = module.get_module_items()
                            for item in items:
                                if item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                                    count += 1
                    except Exception:
                         pass

            else:
                # Modules Mode (Default) - Hybrid Logic
                # 1. Count Module Items
                module_file_ids = set()
                modules = course.get_modules()
                for module in modules:
                    items = module.get_module_items()
                    for item in items:
                        if item.type == 'File':
                            # M-5: one physical copy per file - a duplicate
                            # module link is skipped by the download loop, so
                            # counting it would leave the progress bar short
                            # of 100% at completion.
                            _cid = getattr(item, 'content_id', None)
                            if _cid is not None and _cid in module_file_ids:
                                continue
                            if _cid is not None:
                                module_file_ids.add(_cid)

                            if file_filter != 'study':
                                # Study mode can't verify extension without a slow file fetch;
                                # count is derived from the catch-all section below instead.
                                count += 1
                                
                        elif item.type in ['Page', 'ExternalUrl', 'ExternalTool']:
                            if file_filter != 'study':
                                count += 1
                
                # 2. Count Catch-All Files (Files NOT in modules)
                try:
                    all_files = course.get_files()
                    for file in all_files:
                        if file.id in module_file_ids:
                            continue # Already counted
                        
                        if not file_in_scope(preferred_disk_name(file), file_filter):
                            continue

                        count += 1
                except Exception:
                    pass

        except Exception:
            # Counting is "best effort" for progress bar. 
            pass
        return count
    
    def get_course_total_size_mb(self, course, mode='modules', file_filter='all'):
        """Calculate total size in MB."""
        total_bytes = 0
        try:
            # Try get_files() first
            try:
                files = course.get_files()
                for file in files:
                    if not file_in_scope(preferred_disk_name(file), file_filter):
                        continue
                    total_bytes += getattr(file, 'size', 0) or 0
            except Exception:
                # Fallback to modules
                modules = course.get_modules()
                for module in modules:
                    items = module.get_module_items()
                    for item in items:
                        if item.type == 'File':
                            try:
                                file_obj = course.get_file(item.content_id)
                                if not file_in_scope(preferred_disk_name(file_obj), file_filter):
                                    continue
                                total_bytes += getattr(file_obj, 'size', 0) or 0
                            except Exception:
                                pass
        except Exception:
            pass
        return total_bytes / (1024 * 1024)

    async def download_course_async(self, course, mode, save_dir, progress_callback=None, check_cancellation=None, file_filter='all', debug_mode=False, post_processing_settings=None, secondary_content_settings=None, estimated_size_mb=0):
        """
        Downloads content for a single course asynchronously.

        Args:
            estimated_size_mb: Per-course estimated payload in MB for disk-space
                check. Pass the course-specific value from the caller instead of
                relying on the aggregate ``total_mb`` session-state key, which is
                stale after the first course in a multi-course download run.
        """
        course_name = self._sanitize_filename(course.name)
        base_path = Path(save_dir) / course_name

        from streamlit.runtime.scriptrunner import get_script_run_ctx
        current_ctx = get_script_run_ctx()

        # Check disk space using the caller-supplied per-course estimate.
        # Fall back to the session-state aggregate only as a last resort so we
        # don't silently skip the check when no estimate was provided.
        _estimated_mb = estimated_size_mb or 0
        if not _estimated_mb:
            try:
                import streamlit as _st_disk
                _estimated_mb = _st_disk.session_state.get('total_mb', 0) or 0
            except Exception:
                _estimated_mb = 0
        _estimated_bytes = int(_estimated_mb * 1024 * 1024)
        if not self._check_disk_space(save_dir, required_bytes=_estimated_bytes):
            _free_gb = 0
            try:
                _free_gb = shutil.disk_usage(save_dir).free / (1024 ** 3)
            except Exception:
                pass
            error = DownloadError(
                course.name,
                "Disk Check",
                "Disk Full",
                f'Insufficient disk space. Estimated payload: {_estimated_mb:.0f} MB, '
                f'available: {_free_gb:.1f} GB. Need at least {max(1.0, _estimated_mb * 1.2 / 1024):.1f} GB free.',
                is_app_error=True,
            )
            if progress_callback: progress_callback(error, progress_type='error')
            self._log_error(save_dir, error)
            return
        
        Path(make_long_path(base_path)).mkdir(parents=True, exist_ok=True)

        if check_cancellation and check_cancellation():
            if progress_callback: progress_callback('Download cancelled.')
            return
        
        # --- Sync Run #0: Initialize the Sync DB during the very first download ---
        # This creates .canvas_sync.db and the sync_manifest table so the Sync engine
        # inherits a perfect state when the user later clicks the Sync tab.
        sync_manager = SyncManager(base_path, course.id, course.name)

        # Same-name secondary entity guard: fresh per-course registry so two
        # DISTINCT entities with identical sanitized names get " (1)" suffixes
        # instead of silently overwriting each other (see _save_secondary_entity).
        self._sec_registry = {}

        # Same-FILE guard: {real Canvas file id -> where this run put it}.
        # The phases below each compute their own destination for a file, so
        # the same Canvas id can be requested by the module walk, the Catch-All
        # and a Canvas Content attachment. _download_file_async consults this
        # before every fetch and places a local copy instead of re-downloading.
        self._file_registry = {}
        
        debug_file = (Path(save_dir) / "debug_log.txt") if debug_mode else None
        if debug_mode:
            # Append course header (never wipe - one global log per session)
            log_debug(f"\n{'='*50}\n--- Download: {course.name} (ID: {course.id}) Mode: {mode} ---\n{'='*50}", debug_file)
            log_debug(f"Save Dir: {save_dir}", debug_file)

        downloaded_file_ids = set()
        module_file_ids = set()
        seen_target_paths = set()  # Path-based collision tracking
        module_handled_ids = set()  # Secondary entity IDs already handled via module dispatch
        mb_tracker = {'bytes_downloaded': 0}
        
        # Determine semaphore limit from session state if available, default to 5.
        # Wrapped in try/except because this async function may run on a background
        # thread where Streamlit's session context is not present.
        try:
            import streamlit as _st_sem
            concurrent_limit = int(_st_sem.session_state.get('concurrent_downloads', 5) or 5)
        except Exception:
            concurrent_limit = 5
        # Clamp to a sane range so a corrupted setting can't crash
        # asyncio.Semaphore (rejects non-positive) or fork 1000 sockets.
        concurrent_limit = max(1, min(concurrent_limit, 20))
        sem = asyncio.Semaphore(concurrent_limit)

        # Read max-file-size gate from session state once, store on the
        # manager so every _download_file_async call can apply it without
        # plumbing a parameter through ~7 dispatch sites.
        try:
            import streamlit as _st_sz
            if _st_sz.session_state.get('max_file_size_enabled', False):
                _mb = int(_st_sz.session_state.get('max_file_size_mb', 0) or 0)
                self._max_file_size_bytes = _mb * 1024 * 1024 if _mb > 0 else None
            else:
                self._max_file_size_bytes = None
        except Exception:
            self._max_file_size_bytes = None

        if debug_mode:
            _sz_label = f"{self._max_file_size_bytes // (1024 * 1024)} MB" if self._max_file_size_bytes else "disabled"
            log_debug(
                f"Filter: {file_filter} | Concurrency: {concurrent_limit} | "
                f"Max file size: {_sz_label} | Estimated payload: {_estimated_mb:.0f} MB",
                debug_file,
            )
            if secondary_content_settings:
                _sec_en = [
                    k.replace('download_', '') for k, v in secondary_content_settings.items()
                    if v and k.startswith('download_')
                ]
                _iso = secondary_content_settings.get('isolate_secondary_content', True)
                log_debug(
                    f"Canvas Content: [{', '.join(_sec_en) or 'none'}] | isolate={'yes' if _iso else 'no'}",
                    debug_file,
                )
            else:
                log_debug("Canvas Content: disabled", debug_file)
            if post_processing_settings:
                _pp_en = [
                    k.replace('convert_', '') for k, v in post_processing_settings.items()
                    if v and k.startswith('convert_')
                ]
                log_debug(f"Post-processing: [{', '.join(_pp_en) or 'none'}]", debug_file)
            else:
                log_debug("Post-processing: none", debug_file)

        tasks = []
        timeout = aiohttp.ClientTimeout(total=3600, sock_read=60, sock_connect=15)
        connector = aiohttp.TCPConnector(limit=concurrent_limit, limit_per_host=concurrent_limit, ssl=get_ssl_context())

        async with aiohttp.ClientSession(
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=timeout,
            connector=connector
        ) as session:
            downloaded_files_info = []
            # Whether the Canvas Content phase has already run for this course.
            # A list because a closure may only READ an enclosing local.
            _canvas_content_done = []
            # Derived HERE, unconditionally. The only other spelling of this in
            # download_course_async is `_iso`, which lives inside both an
            # `if debug_mode:` and an `if secondary_content_settings:` - so
            # reading it at the dispatch below raises UnboundLocalError on any
            # run with debug off, aborting the whole course into the generic
            # "Processing Error" handler. Which is exactly what it did.
            _isolate_secondary = bool(
                (secondary_content_settings or {}).get('isolate_secondary_content', True))

            async def _canvas_content_phase():
                """Pages, assignments, announcements … and their attachments.

                A closure because WHERE it runs depends on the mode, and it must
                always run before whatever sweeps the Files tab - see the
                ordering note on the Catch-All. Called from one of the two
                ordinary sites below, plus the 401 fallback.

                **Idempotent, and that is what makes the fallback safe.** When
                the module walk raises 401 the handler retries the course as a
                flat scan, and whether this phase already ran depends on WHERE
                the 401 surfaced: raised by ``get_modules()`` it has not, raised
                later it has. Neither the fallback nor this function can know
                which, so guessing picks a failure - skip and a course with a
                hidden Modules tab silently loses every announcement and
                assignment; call unconditionally and the other case downloads
                all of it twice. Running at most once per course answers both.
                """
                if _canvas_content_done:
                    return
                _canvas_content_done.append(True)
                if not (secondary_content_settings and any(
                        secondary_content_settings.get(k)
                        for k in SECONDARY_CONTENT_DEFAULTS
                        if k.startswith('download_'))):
                    return
                if debug_mode:
                    _sec_active = [
                        k.replace('download_', '') for k, v in secondary_content_settings.items()
                        if v and k.startswith('download_')
                    ]
                    log_debug(f"--- Canvas Content Phase: [{', '.join(_sec_active)}] ---", debug_file)
                try:
                    await self._download_secondary_content(
                        course, base_path, sem, session,
                        progress_callback, mb_tracker, check_cancellation,
                        secondary_content_settings, Path(save_dir),
                        debug_file, sync_manager, module_handled_ids,
                    )
                except Exception as sec_e:
                    err = DownloadError(
                        course.name, "Canvas Content",
                        "Canvas Content Error", str(sec_e),
                        raw_error=sec_e,
                        is_app_error=True,
                    )
                    if progress_callback:
                        progress_callback(err, progress_type='error')
                    self._log_error(save_dir, err)

            try:
                # In flat / folder-structure mode the primary loop IS the
                # Files-tab sweep, so Canvas Content has to claim its
                # attachments ahead of it. (In modules mode it runs later -
                # after the module walk, which is what fills
                # module_handled_ids, and before the Catch-All. Those two modes
                # never populate that set, so nothing is lost by going first.)
                if mode in ('flat', 'files'):
                    await _canvas_content_phase()
                if mode == 'flat':
                    # Only the genuine flat mode opts in. The 401 fallback below
                    # must NOT: it records download_mode='modules', so the analyzer
                    # will expect the prefixed "Page: X.html" form and the writer
                    # has to produce exactly that.
                    downloaded_files_info = await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file, sync_manager=sync_manager, isolate_pages=_isolate_secondary)
                elif mode == 'files':
                    downloaded_files_info = await self._download_folders_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file, sync_manager=sync_manager)
                else:
                    # Modules mode
                    # 1. Fetch Modules
                    modules = None
                    for attempt in range(3):
                        try:
                            modules = course.get_modules()
                            modules = list(modules) # Force fetch
                            break
                        except Exception as e:
                            if attempt < 2:
                                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                            else:
                                raise e

                    for module in modules:
                        if check_cancellation and check_cancellation(): break

                        try:
                            log_debug(f"Processing Module: {module.name} (ID: {module.id})", debug_file)
                            module_name = self._sanitize_filename(module.name)
                            target_path = base_path / module_name
                            Path(make_long_path(target_path)).mkdir(parents=True, exist_ok=True)

                            items = list(module.get_module_items())
                            log_debug(f"Found {len(items)} items in module '{module.name}'", debug_file)
                            for item in items:
                                if check_cancellation and check_cancellation(): break

                                log_debug(f"  - Item: {getattr(item, 'title', 'unknown')} (Type: {getattr(item, 'type', 'unknown')})", debug_file)
                                
                                try:
                                    if item.type == 'File':
                                        if not hasattr(item, 'content_id') or not item.content_id:
                                            # Create Error
                                            err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Content ID", f"Item {getattr(item, 'title', 'unknown')} missing content_id")
                                            if progress_callback: progress_callback(err, progress_type='error')
                                            self._log_error(save_dir, err)
                                            continue
                                        # M-5: one physical copy per Canvas file - FIRST
                                        # linking module wins. A module link is a
                                        # reference to one file, not a second file;
                                        # duplicating per module left every extra copy
                                        # permanently untracked by the sync manifest
                                        # (manifest rows are keyed by canvas_file_id),
                                        # so teacher updates only ever reached one copy.
                                        if item.content_id in module_file_ids:
                                            log_debug(
                                                f"  Duplicate module link skipped (already saved in an earlier module): "
                                                f"{getattr(item, 'title', item.content_id)}", debug_file)
                                            continue
                                        module_file_ids.add(item.content_id)

                                        file_obj = course.get_file(item.content_id)
                                        # Track the ID for the catch-all phase.
                                        downloaded_file_ids.add(file_obj.id)

                                        # Synchronous conflict resolution to prevent data loss.
                                        # Regular files save under the teacher-curated
                                        # display name (what students see in Canvas),
                                        # falling back to the raw upload filename.
                                        base_filename = self._sanitize_filename(preferred_disk_name(file_obj) or 'unknown')
                                        filepath = target_path / base_filename
                                        target_key = str(filepath).lower()

                                        if target_key in seen_target_paths:
                                            counter = 1
                                            while True:
                                                new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                                                new_filepath = target_path / new_name
                                                if str(new_filepath).lower() not in seen_target_paths:
                                                    filepath = new_filepath
                                                    target_key = str(new_filepath).lower()
                                                    break
                                                counter += 1
                                                
                                        seen_target_paths.add(target_key)
                                        log_debug(f"Module file tracked: {filepath.name} (ID: {file_obj.id})", debug_file)
                                        task = asyncio.create_task(self._download_file_async(
                                            sem, session, file_obj, target_path, progress_callback, mb_tracker, file_filter, 
                                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath
                                        ))
                                        tasks.append(task)
                                    
                                    elif item.type == 'Page':
                                        if not module_item_in_scope(item.type, file_filter): continue
                                        if not hasattr(item, 'page_url') or not item.page_url:
                                            # Error
                                            err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Page URL", "Page has no URL")
                                            if progress_callback: progress_callback(err, progress_type='error')
                                            self._log_error(save_dir, err)
                                            continue
                                        
                                        page_obj = course.get_page(item.page_url)
                                        page_id = getattr(page_obj, 'page_id', getattr(page_obj, 'id', 0))
                                        filepath, _, _ = self._save_secondary_entity(
                                            'page', getattr(page_obj, 'title', 'Untitled Page'), getattr(page_obj, 'body', '') or '',
                                            base_path, course_base_path=base_path, sync_manager=sync_manager,
                                            canvas_entity_id=page_id, canvas_updated_at=getattr(page_obj, 'updated_at', '') or '',
                                            progress_callback=progress_callback, debug_file=debug_file, error_root_path=Path(save_dir) if 'save_dir' in locals() else None,
                                            # `isolate=False` is DELIBERATE and must stay in step
                                            # with the two module_map/emitted_filename decisions in
                                            # _get_files_from_modules: a module Page lives in its
                                            # module folder in BOTH isolate modes (and at the course
                                            # root in flat mode, where there is no module folder).
                                            # Changing this alone writes "Pages/X.html" while the
                                            # analyzer still expects "Page: X.html", so every page
                                            # reads as new on every sync, for ever.
                                            course_name=course.name, module_path=target_path, isolate=False, has_attachments=False, metadata_pairs=[],
                                            content_sig=compute_entity_content_sig('page', page_obj)
                                        )
                                        if filepath and path_exists(filepath):
                                            info = CanvasFileInfo(
                                                id=-int(item.id) if hasattr(item, 'id') else 0,
                                                filename=filepath.name,
                                                display_name=getattr(page_obj, 'title', filepath.name),
                                                size=0,
                                                modified_at=getattr(page_obj, 'updated_at', datetime.now(timezone.utc).isoformat()),
                                                url=getattr(item, 'html_url', ''),
                                                content_type="text/html"
                                            )
                                            downloaded_files_info.append((info, filepath))
                                    
                                    elif item.type == 'ExternalUrl':
                                        if not module_item_in_scope(item.type, file_filter): continue
                                        if not hasattr(item, 'external_url') or not item.external_url:
                                             # Error
                                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing External URL", "Link has no URL")
                                             if progress_callback: progress_callback(err, progress_type='error')
                                             self._log_error(save_dir, err)
                                             continue
                                        filepath = self._create_link(item.title, item.external_url, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0, seen_paths=seen_target_paths)
                                        if filepath and path_exists(filepath):
                                            info = CanvasFileInfo(
                                                id=-int(item.id) if hasattr(item, 'id') else 0,
                                                filename=filepath.name,
                                                display_name=item.title,
                                                size=0,
                                                modified_at=datetime.now(timezone.utc).isoformat(),
                                                url=getattr(item, 'external_url', ''),
                                                content_type="application/x-url"
                                            )
                                            downloaded_files_info.append((info, filepath))
                                    
                                    elif item.type == 'ExternalTool':
                                        if not module_item_in_scope(item.type, file_filter): continue
                                        url = getattr(item, 'html_url', None) or getattr(item, 'external_url', None)
                                        if not url:
                                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Missing Tool URL", "External Tool missing launch URL")
                                             if progress_callback: progress_callback(err, progress_type='error')
                                             self._log_error(save_dir, err)
                                             continue
                                        filepath = self._create_link(item.title, url, target_path, progress_callback, error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0, seen_paths=seen_target_paths)
                                        if filepath and path_exists(filepath):
                                            info = CanvasFileInfo(
                                                id=-int(item.id) if hasattr(item, 'id') else 0,
                                                filename=filepath.name,
                                                display_name=item.title,
                                                size=0,
                                                modified_at=datetime.now(timezone.utc).isoformat(),
                                                url=url,
                                                content_type="application/x-url"
                                            )
                                            downloaded_files_info.append((info, filepath))

                                    # --- Secondary Content: Module-aware dispatch ---
                                    elif item.type == 'Assignment':
                                        if secondary_content_settings and secondary_content_settings.get('download_assignments'):
                                            if hasattr(item, 'content_id') and item.content_id:
                                                try:
                                                    isolate = secondary_content_settings.get('isolate_secondary_content', True)
                                                    assignment = course.get_assignment(item.content_id)
                                                    a_id = getattr(assignment, 'id', 0)
                                                    a_name = getattr(assignment, 'name', 'Untitled Assignment')
                                                    description = getattr(assignment, 'description', '') or ''
                                                    updated_at = getattr(assignment, 'updated_at', '') or ''

                                                    # API attachments
                                                    attachments = []
                                                    try:
                                                        raw_att = getattr(assignment, 'attachments', None)
                                                        if raw_att and isinstance(raw_att, list):
                                                            attachments = raw_att
                                                            log_debug(f"  Module Assignment '{a_name}': found {len(attachments)} API attachment(s)", debug_file)
                                                    except Exception:
                                                        pass

                                                    # ── Inline-link extraction (HTML body) ──
                                                    existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                                                    for link_info in _extract_canvas_file_links(description):
                                                        fid = link_info['file_id']
                                                        if fid in existing_att_ids:
                                                            continue
                                                        log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                                                        try:
                                                            canvas_file = course.get_file(fid)
                                                            attachments.append({
                                                                'id': canvas_file.id,
                                                                'url': canvas_file.url,
                                                                'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                                                'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                                                'size': getattr(canvas_file, 'size', 0),
                                                                'modified_at': getattr(canvas_file, 'modified_at', ''),
                                                                'content-type': getattr(canvas_file, 'content_type', ''),
                                                            })
                                                            existing_att_ids.add(canvas_file.id)
                                                        except (Unauthorized, ResourceDoesNotExist):
                                                            log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                                                        except Exception as e:
                                                            log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                                                    has_attachments = bool(attachments)
                                                    if has_attachments:
                                                        log_debug(f"  Module Assignment '{a_name}': {len(attachments)} total attachment(s) (API + inline)", debug_file)

                                                    metadata = [
                                                        ('Due', getattr(assignment, 'due_at', None)),
                                                        ('Points', getattr(assignment, 'points_possible', None)),
                                                        ('Submission Types', ', '.join(
                                                            getattr(assignment, 'submission_types', []) or []
                                                        )),
                                                        ('URL', getattr(assignment, 'html_url', None)),
                                                    ]
                                                    module_target = target_path if not isolate else None
                                                    filepath, syn_id, canvas_updated = self._save_secondary_entity(
                                                        'assignment', a_name,
                                                        assignment_body_html(
                                                            course, assignment, description, debug_file),
                                                        base_path,
                                                        course_base_path=base_path, sync_manager=sync_manager,
                                                        canvas_entity_id=a_id, canvas_updated_at=updated_at,
                                                        progress_callback=progress_callback,
                                                        debug_file=debug_file,
                                                        error_root_path=Path(save_dir),
                                                        course_name=course.name,
                                                        module_path=module_target, isolate=isolate,
                                                        has_attachments=has_attachments,
                                                        metadata_pairs=metadata,
                                                        content_sig=compute_entity_content_sig('assignment', assignment),
                                                    )

                                                    # Record parent HTML to DB manifest
                                                    if filepath and sync_manager:
                                                        try:
                                                            rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                                                            sync_manager.record_downloaded_file(
                                                                canvas_file_id=syn_id,
                                                                canvas_filename=Path(filepath).name,
                                                                local_path=rel_path,
                                                                canvas_updated_at=canvas_updated,
                                                                original_size=0,
                                                            )
                                                        except Exception as db_err:
                                                            log_debug(f"DB record error for module assignment '{a_name}': {db_err}", debug_file)

                                                    # Queue attachment downloads
                                                    if filepath and attachments:
                                                        attach_dir = filepath.parent
                                                        for att in attachments:
                                                            raw_id = att.get('id')
                                                            att_url = att.get('url', '')
                                                            att_filename = att.get('filename', att.get('display_name', 'attachment'))
                                                            if not att_url or not raw_id:
                                                                continue

                                                            att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                                                            if not isolate:
                                                                routing = _ENTITY_ROUTING['assignment']
                                                                att_filename = f"{routing['prefix']}: {self._sanitize_filename(a_name)} - {att_filename}"

                                                            att_file_obj = types.SimpleNamespace(
                                                                id=att_id,
                                                                url=att_url,
                                                                filename=att_filename,
                                                                display_name=att.get('display_name', att_filename),
                                                                size=att.get('size', 0),
                                                                modified_at=att.get('modified_at', updated_at),
                                                                md5=None,
                                                                content_type=att.get('content-type', ''),
                                                                folder_id=None,
                                                                name_locked=True,
                                                            )

                                                            att_filepath = attach_dir / self._sanitize_filename(att_filename)
                                                            if progress_callback:
                                                                progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))

                                                            task = asyncio.create_task(self._download_file_async(
                                                                sem, session, att_file_obj, attach_dir,
                                                                progress_callback, mb_tracker, 'attachment',
                                                                error_root_path=Path(save_dir),
                                                                course_name=course.name, debug_file=debug_file,
                                                                sync_manager=sync_manager,
                                                                course_base_path=base_path,
                                                                explicit_filepath=att_filepath,
                                                            ))
                                                            tasks.append(task)

                                                    module_handled_ids.add(a_id)
                                                except Exception as ae:
                                                    log_debug(f"Module Assignment dispatch error: {ae}", debug_file)
                                                    logger.warning(f"Assignment dispatch failed for '{getattr(item, 'title', '?')}': {ae}")
                                                    _ae_err = DownloadError(course.name, getattr(item, 'title', 'Assignment'), "Assignment Dispatch Error", str(ae), raw_error=ae)
                                                    if progress_callback: progress_callback(_ae_err, progress_type='error')
                                                    self._log_error(save_dir, _ae_err)

                                    elif item.type == 'Quiz':
                                        if secondary_content_settings and secondary_content_settings.get('download_quizzes'):
                                            if hasattr(item, 'content_id') and item.content_id:
                                                try:
                                                    isolate = secondary_content_settings.get('isolate_secondary_content', True)
                                                    quiz = course.get_quiz(item.content_id)
                                                    q_id = getattr(quiz, 'id', 0)
                                                    q_title = getattr(quiz, 'title', 'Untitled Quiz')
                                                    q_desc = getattr(quiz, 'description', '') or ''
                                                    updated_at = getattr(quiz, 'updated_at', '') or ''

                                                    # API attachments
                                                    attachments = []
                                                    try:
                                                        raw_att = getattr(quiz, 'attachments', None)
                                                        if raw_att and isinstance(raw_att, list):
                                                            attachments = raw_att
                                                    except Exception:
                                                        pass

                                                    # ── Inline-link extraction (HTML body) ──
                                                    existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                                                    for link_info in _extract_canvas_file_links(q_desc):
                                                        fid = link_info['file_id']
                                                        if fid in existing_att_ids:
                                                            continue
                                                        try:
                                                            canvas_file = course.get_file(fid)
                                                            attachments.append({
                                                                'id': canvas_file.id,
                                                                'url': canvas_file.url,
                                                                'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                                                'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                                                'size': getattr(canvas_file, 'size', 0),
                                                                'modified_at': getattr(canvas_file, 'modified_at', ''),
                                                                'content-type': getattr(canvas_file, 'content_type', ''),
                                                            })
                                                            existing_att_ids.add(canvas_file.id)
                                                        except (Unauthorized, ResourceDoesNotExist):
                                                            pass
                                                        except Exception:
                                                            pass

                                                    has_attachments = bool(attachments)

                                                    metadata = [
                                                        ('Points', getattr(quiz, 'points_possible', None)),
                                                        ('Due', getattr(quiz, 'due_at', None)),
                                                        ('URL', getattr(quiz, 'html_url', None)),
                                                    ]
                                                    module_target = target_path if not isolate else None
                                                    filepath, syn_id, canvas_updated = self._save_secondary_entity(
                                                        'quiz', q_title,
                                                        quiz_body_html(quiz, debug_file),
                                                        base_path,
                                                        course_base_path=base_path, sync_manager=sync_manager,
                                                        canvas_entity_id=q_id, canvas_updated_at=updated_at,
                                                        progress_callback=progress_callback,
                                                        debug_file=debug_file,
                                                        error_root_path=Path(save_dir),
                                                        course_name=course.name,
                                                        module_path=module_target, isolate=isolate,
                                                        has_attachments=has_attachments,
                                                        metadata_pairs=metadata,
                                                        content_sig=compute_entity_content_sig('quiz', quiz),
                                                    )

                                                    # Record parent HTML to DB manifest
                                                    if filepath and sync_manager:
                                                        try:
                                                            rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                                                            sync_manager.record_downloaded_file(
                                                                canvas_file_id=syn_id,
                                                                canvas_filename=Path(filepath).name,
                                                                local_path=rel_path,
                                                                canvas_updated_at=canvas_updated,
                                                                original_size=0,
                                                            )
                                                        except Exception:
                                                            pass

                                                    # Queue attachment downloads
                                                    if filepath and attachments:
                                                        attach_dir = filepath.parent
                                                        for att in attachments:
                                                            raw_id = att.get('id')
                                                            att_url = att.get('url', '')
                                                            att_filename = att.get('filename', att.get('display_name', 'attachment'))
                                                            if not att_url or not raw_id:
                                                                continue
                                                            att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id
                                                            if not isolate:
                                                                routing = _ENTITY_ROUTING['quiz']
                                                                att_filename = f"{routing['prefix']}: {self._sanitize_filename(q_title)} - {att_filename}"
                                                            att_file_obj = types.SimpleNamespace(
                                                                id=att_id, url=att_url, filename=att_filename,
                                                                display_name=att.get('display_name', att_filename),
                                                                size=att.get('size', 0), modified_at=att.get('modified_at', updated_at),
                                                                md5=None, content_type=att.get('content-type', ''),
                                                                folder_id=None, name_locked=True,
                                                            )
                                                            att_filepath = attach_dir / self._sanitize_filename(att_filename)
                                                            if progress_callback:
                                                                progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))
                                                            task = asyncio.create_task(self._download_file_async(
                                                                sem, session, att_file_obj, attach_dir,
                                                                progress_callback, mb_tracker, 'attachment',
                                                                error_root_path=Path(save_dir),
                                                                course_name=course.name, debug_file=debug_file,
                                                                sync_manager=sync_manager, course_base_path=base_path,
                                                                explicit_filepath=att_filepath,
                                                            ))
                                                            tasks.append(task)

                                                    module_handled_ids.add(q_id)
                                                except Exception as qe:
                                                    log_debug(f"Module Quiz dispatch error: {qe}", debug_file)
                                                    logger.warning(f"Quiz dispatch failed for '{getattr(item, 'title', '?')}': {qe}")
                                                    _qe_err = DownloadError(course.name, getattr(item, 'title', 'Quiz'), "Quiz Dispatch Error", str(qe), raw_error=qe)
                                                    if progress_callback: progress_callback(_qe_err, progress_type='error')
                                                    self._log_error(save_dir, _qe_err)

                                    elif item.type == 'Discussion':
                                        if secondary_content_settings and secondary_content_settings.get('download_discussions'):
                                            if hasattr(item, 'content_id') and item.content_id:
                                                try:
                                                    isolate = secondary_content_settings.get('isolate_secondary_content', True)
                                                    topic = resolve_discussion_topic(
                                                        course, item.content_id, debug_file)
                                                    t_id = getattr(topic, 'id', 0)
                                                    title = getattr(topic, 'title', 'Untitled Discussion')
                                                    message = getattr(topic, 'message', '') or ''
                                                    message += await asyncio.to_thread(safe_thread_wrapper, self._build_discussion_replies_html_sync, current_ctx, topic, debug_file)
                                                    updated_at = (getattr(topic, 'last_reply_at', '')
                                                                  or getattr(topic, 'updated_at', '') or '')

                                                    # API attachments
                                                    attachments = []
                                                    try:
                                                        raw_att = getattr(topic, 'attachments', None)
                                                        if raw_att and isinstance(raw_att, list):
                                                            attachments = raw_att
                                                    except Exception:
                                                        pass

                                                    # ── Inline-link extraction (HTML body) ──
                                                    existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                                                    for link_info in _extract_canvas_file_links(message):
                                                        fid = link_info['file_id']
                                                        if fid in existing_att_ids:
                                                            continue
                                                        try:
                                                            canvas_file = course.get_file(fid)
                                                            attachments.append({
                                                                'id': canvas_file.id,
                                                                'url': canvas_file.url,
                                                                'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                                                                'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                                                                'size': getattr(canvas_file, 'size', 0),
                                                                'modified_at': getattr(canvas_file, 'modified_at', ''),
                                                                'content-type': getattr(canvas_file, 'content_type', ''),
                                                            })
                                                            existing_att_ids.add(canvas_file.id)
                                                        except (Unauthorized, ResourceDoesNotExist):
                                                            pass
                                                        except Exception:
                                                            pass

                                                    has_attachments = bool(attachments)

                                                    metadata = [
                                                        ('Posted', getattr(topic, 'posted_at', None)),
                                                        ('Replies', getattr(topic, 'discussion_subentry_count', None)),
                                                        ('URL', getattr(topic, 'html_url', None)),
                                                    ]
                                                    module_target = target_path if not isolate else None
                                                    filepath, syn_id, canvas_updated = self._save_secondary_entity(
                                                        'discussion', title, message, base_path,
                                                        course_base_path=base_path, sync_manager=sync_manager,
                                                        canvas_entity_id=t_id, canvas_updated_at=updated_at,
                                                        progress_callback=progress_callback,
                                                        debug_file=debug_file,
                                                        error_root_path=Path(save_dir),
                                                        course_name=course.name,
                                                        module_path=module_target, isolate=isolate,
                                                        has_attachments=has_attachments,
                                                        metadata_pairs=metadata,
                                                        content_sig=compute_entity_content_sig('discussion', topic),
                                                    )

                                                    # Record parent HTML to DB manifest
                                                    if filepath and sync_manager:
                                                        try:
                                                            rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                                                            sync_manager.record_downloaded_file(
                                                                canvas_file_id=syn_id,
                                                                canvas_filename=Path(filepath).name,
                                                                local_path=rel_path,
                                                                canvas_updated_at=canvas_updated,
                                                                original_size=0,
                                                            )
                                                        except Exception:
                                                            pass

                                                    # Queue attachment downloads
                                                    if filepath and attachments:
                                                        attach_dir = filepath.parent
                                                        for att in attachments:
                                                            raw_id = att.get('id')
                                                            att_url = att.get('url', '')
                                                            att_filename = att.get('filename', att.get('display_name', 'attachment'))
                                                            if not att_url or not raw_id:
                                                                continue
                                                            att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id
                                                            if not isolate:
                                                                routing = _ENTITY_ROUTING['discussion']
                                                                att_filename = f"{routing['prefix']}: {self._sanitize_filename(title)} - {att_filename}"
                                                            att_file_obj = types.SimpleNamespace(
                                                                id=att_id, url=att_url, filename=att_filename,
                                                                display_name=att.get('display_name', att_filename),
                                                                size=att.get('size', 0), modified_at=att.get('modified_at', updated_at),
                                                                md5=None, content_type=att.get('content-type', ''),
                                                                folder_id=None, name_locked=True,
                                                            )
                                                            att_filepath = attach_dir / self._sanitize_filename(att_filename)
                                                            if progress_callback:
                                                                progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))
                                                            task = asyncio.create_task(self._download_file_async(
                                                                sem, session, att_file_obj, attach_dir,
                                                                progress_callback, mb_tracker, 'attachment',
                                                                error_root_path=Path(save_dir),
                                                                course_name=course.name, debug_file=debug_file,
                                                                sync_manager=sync_manager, course_base_path=base_path,
                                                                explicit_filepath=att_filepath,
                                                            ))
                                                            tasks.append(task)

                                                    module_handled_ids.add(t_id)
                                                except Exception as de:
                                                    log_debug(f"Module Discussion dispatch error: {de}", debug_file)
                                                    logger.warning(f"Discussion dispatch failed for '{getattr(item, 'title', '?')}': {de}")
                                                    _de_err = DownloadError(course.name, getattr(item, 'title', 'Discussion'), "Discussion Dispatch Error", str(de), raw_error=de)
                                                    if progress_callback: progress_callback(_de_err, progress_type='error')
                                                    self._log_error(save_dir, _de_err)
                                        
                                except Exception as item_e:
                                    err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Item Processing Error", str(item_e), raw_error=item_e)
                                    if progress_callback: progress_callback(err, progress_type='error')
                                    self._log_error(save_dir, err)

                        except Exception as module_e:
                             err = DownloadError(course.name, getattr(module, 'name', 'unknown'), "Module Error", str(module_e), raw_error=module_e)
                             if progress_callback: progress_callback(err, progress_type='error')
                             self._log_error(save_dir, err)
                             
                # Wait for file downloads
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                            if progress_callback: progress_callback(err, progress_type='error')
                            self._log_error(save_dir, err)
                        elif result:
                            downloaded_files_info.append(result)


                # ---- CANVAS CONTENT (modules mode: after the module walk,
                #      before the Catch-All - see _canvas_content_phase) ----
                await _canvas_content_phase()

                # ---- HYBRID MODE CATCH-ALL STARTED ----
                # Runs LAST, after Canvas Content, and the order is load-bearing.
                # A Files-tab file can also be an announcement / assignment /
                # quiz / discussion / submission attachment. Whichever phase goes
                # first computes its own destination for it, and the one that
                # follows cannot know - so with the sweep first, the same file
                # was fetched twice, 21 seconds apart, and landed as two copies
                # (measured on course 46396, ids 1784620 and 1807289). Going
                # last, the sweep can see what Canvas Content already claimed,
                # exactly as it has always been able to see the module walk's.
                try:
                    log_debug("Starting Catch-All Phase for non-module files...", debug_file)
                    if progress_callback: progress_callback('Scanning remaining files...', progress_type='log')
                    
                    # Modules mode only: the catch-all sweeps files NOT linked
                    # from any module into the course root. In 'flat'/'files'
                    # modes the primary loop already enumerated get_files()
                    # directly - running the catch-all there would re-scan
                    # everything and, for 'files' (folder-structure) mode,
                    # re-download the entire course into the root because
                    # downloaded_file_ids is only populated by the modules loop.
                    # ('files' is not currently reachable from the UI, but a
                    # legacy preset could still carry it - this guard makes it
                    # safe either way.)
                    all_files_paginator = course.get_files() if mode == 'modules' else []
                    catch_all_tasks = []

                    # Pre-compute ID sets once - avoids O(N×M) set
                    # reconstruction on every loop iteration.
                    _downloaded_ids = {int(i) for i in downloaded_file_ids}
                    _module_ids = {int(i) for i in module_file_ids}

                    for file in all_files_paginator:
                        if check_cancellation and check_cancellation(): break

                        if int(file.id) in _downloaded_ids or int(file.id) in _module_ids:
                            log_debug(f"Catch-All skipping module file: {file.filename} (ID: {file.id})", debug_file)
                            continue # Already downloaded in a module

                        if self._defer_to_canvas_content(file, debug_file):
                            continue

                        # Synchronous conflict resolution to prevent data loss.
                        base_filename = self._sanitize_filename(preferred_disk_name(file) or 'unknown')
                        filepath = base_path / base_filename
                        target_key = str(filepath).lower()

                        if target_key in seen_target_paths:
                            counter = 1
                            while True:
                                new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                                new_filepath = base_path / new_name
                                if str(new_filepath).lower() not in seen_target_paths:
                                    filepath = new_filepath
                                    target_key = str(new_filepath).lower()
                                    break
                                counter += 1
                                
                        seen_target_paths.add(target_key)
                        log_debug(f"Catch-All found new file: {filepath.name} (ID: {file.id})", debug_file)
                        
                        # Download to course root
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, file, base_path, progress_callback, mb_tracker, file_filter, 
                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath
                        ))
                        catch_all_tasks.append(task)
                    
                    if catch_all_tasks:
                        log_debug(f"Downloading {len(catch_all_tasks)} catch-all files...", debug_file)
                        results = await asyncio.gather(*catch_all_tasks, return_exceptions=True)
                        for result in results:
                            if isinstance(result, Exception):
                                err = DownloadError(course.name, "Catch-All Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                                if progress_callback: progress_callback(err, progress_type='error')
                                self._log_error(save_dir, err)
                            elif result:
                                downloaded_files_info.append(result)

                    else:
                        log_debug("No partial/non-module files found.", debug_file)

                except Exception as e:
                    log_debug(f"Catch-All Phase Error: {e}", debug_file)
                    error_msg = str(e).lower()
                    if "unauthorized" in error_msg or "401" in error_msg or "user not authorised" in error_msg:
                        # Just log it, DO NOT add to user's download_errors.txt
                        _msg = f"Files tab restricted for '{course.name}' - skipping catch-all phase."
                        logger.warning(_msg)
                        if progress_callback:
                            progress_callback(_msg, progress_type='log')
                    else:
                        # Handle actual unexpected errors
                        err = DownloadError(course.name, "Catch-All Scan", "Hybrid Mode Error", str(e), raw_error=e, is_app_error=True)
                        self._log_error(save_dir, err)
                # ---- HYBRID MODE CATCH-ALL ENDED ----

                if debug_mode:
                    _total_dl_count = len(downloaded_files_info)
                    _total_mb_dl = mb_tracker.get('bytes_downloaded', 0) / (1024 * 1024)
                    log_debug(
                        f"--- Download Complete: {course.name} | "
                        f"{_total_dl_count} items | {_total_mb_dl:.1f} MB downloaded ---",
                        debug_file,
                    )

            except Exception as e:
                 is_unauthorized = "unauthorized" in str(e).lower() or (hasattr(e, 'status_code') and e.status_code == 401)
                 if is_unauthorized and mode != 'flat':
                     # Fallback to flat
                     msg = 'Modules tab is hidden/unauthorized. Attempting to download files directly...'
                     if progress_callback: progress_callback(msg, progress_type='log')
                     # Log the partial failure
                     err = DownloadError(course.name, "Modules Access", "401 Unauthorized", "Modules locked, falling back to file scan.", raw_error=e)
                     self._log_error(save_dir, err)

                     # Canvas Content BEFORE the flat sweep, exactly as the
                     # ordinary flat path does it - the sweep must never reach a
                     # file an attachment is going to claim. Safe to call here
                     # because the phase runs at most once per course: if the
                     # 401 came from get_modules() this is the only chance it
                     # gets, and if it came later this is a no-op. Without it a
                     # course with a hidden Modules tab downloaded its files and
                     # silently none of its announcements or assignments.
                     await _canvas_content_phase()
                     downloaded_files_info.extend(await self._download_flat_async(course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter, error_root_path=Path(save_dir), debug_file=debug_file, sync_manager=sync_manager))
                 else:
                     err = DownloadError(course.name, "Course Download", "Processing Error", str(e), raw_error=e, is_app_error=True)
                     if progress_callback: progress_callback(err, progress_type='error')
                     self._log_error(save_dir, err)
            
            # --- Sync Run #0: Save the download mode and sync contract ---
            try:
                sync_manager._save_metadata('download_mode', mode)
                # Save the full "Sync Contract" - all settings used during this download
                if post_processing_settings:
                    import json
                    sync_manager._save_metadata('sync_contract', json.dumps(post_processing_settings))
                # Save the secondary content contract
                if secondary_content_settings:
                    import json
                    sync_manager._save_metadata('secondary_content_contract', json.dumps(secondary_content_settings))
            except Exception as e:
                logger.warning(f"Could not save sync contract to DB for '{course.name}': {e}")
                log_debug(f"Warning: Could not save sync metadata: {e}", debug_file)

    async def download_isolated_batch_async(self, course, error_queue, save_dir, progress_callback=None, check_cancellation=None, debug_mode=False, mb_tracker=None):
        """
        Targeted retry for specifically failed items queued in error_queue.
        """
        # Reset discovery-error counter at the start of each batch so the
        # return value reflects only this run.  Without this reset the
        # counter accumulates across reused CanvasManager instances and the
        # UI overstates skipped-discovery counts.
        self.skipped_discovery_errors = 0
        # Same reason: a retry batch re-fetches items that FAILED, so nothing
        # here can legitimately be served from the previous course's
        # already-placed registry. Start empty rather than inherit.
        self._file_registry = {}

        course_name = self._sanitize_filename(course.name)
        base_path = Path(save_dir) / course_name

        debug_file = (Path(save_dir) / "debug_log.txt") if debug_mode else None
        
        # We instantiate a local sync_manager so files downloaded here are logged
        try:
            sync_manager = SyncManager(base_path, course.id, course.name)
        except Exception as e:
            log_debug(f"Failed to initialize SyncManager during isolated batch: {e}", debug_file)
            sync_manager = None
        
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx
        
        # Streamlit Context Safety Assert:
        # Before accessing any session states or spawning sub-tasks, guarantee thread bounds.
        current_ctx = get_script_run_ctx()
        if not current_ctx:
            raise RuntimeError("CRITICAL THREAD LEAK: Streamlit ScriptRunContext is missing in download_isolated_batch_async.")

        try:
            import streamlit as _st_iso
            concurrent_limit = int(_st_iso.session_state.get('concurrent_downloads', 5) or 5)
        except Exception:
            concurrent_limit = 5
        # Final safety net: clamp to a sane range so a corrupted setting can't
        # crash asyncio.Semaphore (rejects non-positive) or fork 1000 sockets.
        concurrent_limit = max(1, min(concurrent_limit, 20))
        sem = asyncio.Semaphore(concurrent_limit)
        tasks = []
        timeout = aiohttp.ClientTimeout(total=3600, sock_read=60, sock_connect=15)

        # Mirror the size-gate setup from download_course_async so the
        # retry path honors the same limit.
        try:
            import streamlit as _st_iso_sz
            if _st_iso_sz.session_state.get('max_file_size_enabled', False):
                _mb = int(_st_iso_sz.session_state.get('max_file_size_mb', 0) or 0)
                self._max_file_size_bytes = _mb * 1024 * 1024 if _mb > 0 else None
            else:
                self._max_file_size_bytes = None
        except Exception:
            self._max_file_size_bytes = None

        if mb_tracker is None:
            mb_tracker = {'bytes_downloaded': 0}


        if debug_mode:
            log_debug(f"\n{'='*50}\n--- Isolated Retry Mode for {course.name} ---\n{'='*50}", debug_file)

        connector = aiohttp.TCPConnector(limit=concurrent_limit, limit_per_host=concurrent_limit, ssl=get_ssl_context())
        async with aiohttp.ClientSession(
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=timeout,
            connector=connector
        ) as session:
            for error_obj in error_queue:
                if check_cancellation and check_cancellation():
                    break
                
                context = getattr(error_obj, 'context', {})
                file_dict = context.get('file_dict')
                filepath_str = context.get('filepath')
                file_filter = context.get('file_filter', 'all')
                
                if file_dict and filepath_str:
                    filepath = Path(filepath_str)
                    
                    # Reconstruct lightweight CanvasFileInfo mock object safely
                    file_obj = CanvasFileInfo(
                        id=file_dict.get('id', 0),
                        filename=file_dict.get('filename', ''),
                        display_name=file_dict.get('display_name', file_dict.get('filename', '')),
                        size=file_dict.get('size', 0),
                        modified_at=file_dict.get('modified_at', None),
                        md5=file_dict.get('md5', None),
                        url=file_dict.get('url', ''),
                        content_type=file_dict.get('content-type', ''),
                        folder_id=file_dict.get('folder_id', None)
                    )
                    
                    # Ensure the explicitly passed parent directory actually exists on disk
                    # to prevent FileNotFoundError during aiofiles.open writes
                    Path(make_long_path(filepath.parent)).mkdir(parents=True, exist_ok=True)
                    
                    from core.sync_manager import secondary_id_type as _retry_sec_type
                    _retry_etype = _retry_sec_type(file_obj.id) if file_obj.id < 0 else None
                    if file_obj.id < 0 and _retry_etype != 'attachment':
                        # Synthetic entity - Route differently.
                        # NOTE: 'attachment'-range negative IDs are REAL Canvas
                        # files (Mode B) and deliberately fall through to the
                        # else-branch below, which refreshes the signed URL
                        # (mapping the synthetic ID back to the raw file ID)
                        # and downloads the actual bytes.
                        etype = _retry_etype

                        if etype == 'module_item':
                            # Legacy synthetic entities (Pages or ExternalURLs)
                            # Synchronously write standard shortcuts/stubs to disk to prevent brittle API refetches.
                            try:
                                url_to_save = file_obj.url
                                ext = filepath.suffix.lower()
                                
                                # Write file formats based directly on extension
                                if ext == '.html':
                                    content = f'<meta http-equiv="refresh" content="0; url={html.escape(url_to_save, quote=True)}">'
                                    async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                        await f.write(content)
                                elif ext == '.url':
                                    _safe_url = url_to_save.replace('\r', '').replace('\n', '%0A')
                                    content = f'[InternetShortcut]\nURL={_safe_url}'
                                    async with aiofiles.open(str(make_long_path(filepath)), 'w', encoding='utf-8') as f:
                                        await f.write(content)
                                elif ext == '.webloc':
                                    import plistlib
                                    content = plistlib.dumps(
                                        {'URL': url_to_save},
                                        fmt=plistlib.FMT_XML,
                                    )
                                    async with aiofiles.open(str(make_long_path(filepath)), 'wb') as f:
                                        await f.write(content)
                                
                                # Do NOT append a task; this item is now done synchronously. 
                                if progress_callback:
                                    progress_callback(f"Saved Link: {filepath.name}", progress_type='download', explicit_filepath=str(filepath.resolve()))
                            
                            except Exception as e:
                                err = DownloadError(course.name, getattr(file_obj, 'filename', 'unknown'), "Legacy Entity Save Error", str(e), raw_error=e)
                                if progress_callback: progress_callback(err, progress_type='error')
                                self._log_error(save_dir, err)
                        else:
                            # Modern secondary entities (actively re-fetched inside the function using raw_id)
                            secondary_settings = {'isolate_secondary_content': True}
                            try:
                                sec_filepath, sec_id, sec_attachments, canvas_updated = await asyncio.to_thread(
                                    safe_thread_wrapper,
                                    self.download_secondary_entity,
                                    current_ctx,
                                    course, file_obj, filepath.parent,
                                    sync_manager, secondary_settings,
                                    progress_callback, debug_file, Path(save_dir), course.name
                                )
                                
                                # 1. The ACID Commit
                                if sync_manager and sec_id and canvas_updated is not None and sec_filepath:
                                    try:
                                        rel_path = str(sec_filepath.relative_to(base_path)).replace('\\', '/')
                                        await asyncio.to_thread(
                                            sync_manager.record_downloaded_file,
                                            canvas_file_id=sec_id,
                                            canvas_filename=sec_filepath.name,
                                            local_path=rel_path,
                                            canvas_updated_at=canvas_updated,
                                            original_size=0
                                        )
                                    except Exception as db_err:
                                        if debug_mode: log_debug(f"DB Commit failed during retry: {db_err}", debug_file)
                                
                                # 2. Dynamic Queue Injection (Await-and-Inject)
                                if sec_attachments:
                                    attach_dir = sec_filepath.parent if sec_filepath else filepath.parent
                                    for att in sec_attachments:
                                        att_id = att.get('id')
                                        att_url = att.get('url', '')
                                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                                        if not att_url or not att_id:
                                            continue
                                            
                                        att_info = CanvasFileInfo(
                                            id=att_id,
                                            filename=att_filename,
                                            display_name=att.get('display_name', att_filename),
                                            size=att.get('size', 0),
                                            modified_at=att.get('modified_at', ''),
                                            url=att_url,
                                            content_type=att.get('content-type', '')
                                        )
                                        
                                        # Progress Bar Integrity
                                        if progress_callback:
                                            progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))
                                            
                                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                                        
                                        att_task = asyncio.create_task(self._download_file_async(
                                            sem, session, att_info, attach_dir, progress_callback, mb_tracker, file_filter, 
                                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=att_filepath,
                                            check_cancellation=check_cancellation
                                        ))
                                        tasks.append(att_task)

                            except Exception as sec_e:
                                err = DownloadError(course.name, getattr(file_obj, 'filename', 'unknown'), "Canvas Content Retry Error", str(sec_e), raw_error=sec_e)
                                if progress_callback: progress_callback(err, progress_type='error')
                                self._log_error(save_dir, err)
                    else:
                        # Refresh URL securely using the safe_thread_wrapper to preserve context for logging
                        try:
                            fetch_id = file_obj.id
                            if fetch_id < 0:
                                from core.sync_manager import secondary_id_type, SECONDARY_ID_OFFSETS
                                if secondary_id_type(fetch_id) == 'attachment':
                                    fetch_id = abs(fetch_id) - SECONDARY_ID_OFFSETS['attachment']
                            
                            fresh_file = await asyncio.to_thread(safe_thread_wrapper, course.get_file, current_ctx, fetch_id)
                            fresh_url = getattr(fresh_file, 'url', '')
                            if not fresh_url:
                                raise ValueError("Canvas API returned an empty URL for this item.")
                            
                            file_obj.url = fresh_url
                            if debug_mode: log_debug(f"Successfully refreshed URL for {file_obj.filename}", debug_file)
                        except Exception as e:
                            # HARD-FAIL CONSTRAINT: Do NOT fallback to stale URL. It will just trigger 403 backoff loops.
                            err = DownloadError(course.name, filepath.name, "URL Expiration", f"Could not refresh expired URL: {e}", raw_error=e)
                            if progress_callback: progress_callback(err, progress_type='error', file_size=file_obj.size)
                            self._log_error(save_dir, err)
                            continue # Skip to the next file immediately
                            
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, file_obj, filepath.parent, progress_callback, mb_tracker, file_filter, 
                            error_root_path=Path(save_dir), course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath,
                            check_cancellation=check_cancellation
                        ))
                        tasks.append(task)
                else:
                    # Discovery error. Lacks file context. Skip and tally.
                    if 'skipped_discovery_errors' not in getattr(self, '__dict__', {}):
                        self.skipped_discovery_errors = 0
                    self.skipped_discovery_errors += 1
            
            if tasks:
                _retry_results = await asyncio.gather(*tasks, return_exceptions=True)
                for _rr in _retry_results:
                    if isinstance(_rr, Exception):
                        logger.error(f"Isolated retry task failed: {_rr}")
                        if progress_callback:
                            _rr_err = DownloadError(
                                getattr(course, 'name', 'Unknown'), "Retry Task",
                                "Async Retry Error", str(_rr), raw_error=_rr,
                            )
                            progress_callback(_rr_err, progress_type='error')

            return getattr(self, 'skipped_discovery_errors', 0)

    async def _download_folders_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all', error_root_path=None, debug_file=None, sync_manager=None):
        """Downloads files preserving actual folder structure."""
        tasks = []
        downloaded = []
        folder_map = {}
        log_debug(f"Starting Folders Download for {course.name}", debug_file)

        # 1. Fetch Folders
        try:
            if progress_callback: progress_callback('Fetching folder structure...')
            all_folders = course.get_folders()
            for folder in all_folders:
                full_name = getattr(folder, 'full_name', '')
                if full_name.startswith("course files"):
                    rel_path = full_name[len("course files"):].strip('/')
                else:
                    rel_path = full_name
                folder_map[folder.id] = rel_path
            log_debug(f"Mapped {len(folder_map)} folders.", debug_file)
        except Exception as e:
            err = DownloadError(course.name, "Folder Structure", "Fetch Error", f"Could not fetch folders: {e}", raw_error=e, is_app_error=True)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            # Continue to allow flat file download if possible?
            # If folder fetch failed, likely file fetch will too, but let's try.

        # 2. Fetch and Download Files
        try:
            if progress_callback: progress_callback('Fetching file list...')
            files_paginator = course.get_files()
            
            for file in files_paginator:
                if check_cancellation and check_cancellation(): break
                # The Files-tab sweep in folder-structure mode - yields to
                # Canvas Content exactly as the flat loop and the Catch-All do.
                if self._defer_to_canvas_content(file, debug_file):
                    continue
                try:
                    # Calculate path
                    folder_id = getattr(file, 'folder_id', None)
                    rel_folder_path = folder_map.get(folder_id, "")
                    path_parts = [self._sanitize_filename(p) for p in rel_folder_path.split('/') if p]
                    target_path = base_path
                    for part in path_parts:
                        target_path = target_path / part
                    Path(make_long_path(target_path)).mkdir(parents=True, exist_ok=True)

                    task = asyncio.create_task(self._download_file_async(
                        sem, session, file, target_path, progress_callback, mb_tracker, file_filter,
                        error_root_path=error_root_path, course_name=course.name, debug_file=debug_file,
                        sync_manager=sync_manager, course_base_path=base_path, check_cancellation=check_cancellation
                    ))
                    tasks.append(task)
                except Exception as e:
                    err = DownloadError(course.name, getattr(file, 'filename', 'unknown'), "Queue Error", str(e), raw_error=e)
                    if progress_callback: progress_callback(err, progress_type='error')
                    self._log_error(error_root_path, err)
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                        if progress_callback: progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)
                    elif result:
                        downloaded.append(result)


        except Exception as e:
            err = DownloadError(course.name, "File List", "Fetch Error", str(e), raw_error=e, is_app_error=True)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

        return downloaded

    async def _download_flat_async(self, course, base_path, sem, session, progress_callback, mb_tracker, check_cancellation, file_filter='all', error_root_path=None, debug_file=None, sync_manager=None, isolate_pages=False):
        """Downloads all files to the root folder.

        ``isolate_pages`` routes module Pages to their category folder. It is
        off by default so the 401 fallback and any other caller keep today's
        layout unless they opt in, and it must agree with what
        ``_get_files_from_modules`` emits for the same run - the analyzer's
        expected path comes from there, and the two disagreeing makes every
        page read as new on every sync.
        """
        tasks = []
        downloaded = []
        log_debug(f"Starting Flat Download for {course.name}", debug_file)
        
        
        try:
            files = None
            for attempt in range(3):
                try:
                    files = course.get_files()
                    break
                except Exception:
                    if attempt < 2:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    else:
                        files = []
                        # Debug-log only: a restricted Files tab is a normal Canvas
                        # course configuration (module scan covers it), not
                        # something the user needs to see in the live log.
                        log_debug("Files tab restricted (401?), falling back to module scan.", debug_file)

            downloaded_ids = set()
            seen_flat_paths = set()  # Path-based dedup for flat mode
            # Wrap iteration separately: course.get_files() returns a lazy PaginatedList with no
            # network I/O, so the retry loop above never actually tests connectivity.  The first
            # real HTTP request fires here when the iterator is consumed.  Without this inner
            # try the module-scan fallback below would be silently skipped on a 401/network error.
            try:
                for file in files:
                    if check_cancellation and check_cancellation(): break
                    if getattr(file, 'id', None):
                        downloaded_ids.add(file.id)

                    # This loop IS the Files-tab sweep in flat mode, so Canvas
                    # Content runs ahead of it (see download_course_async) and
                    # it yields the same way the Catch-All does. Before the name
                    # reservation below, so a deferred file leaves its name free.
                    if self._defer_to_canvas_content(file, debug_file):
                        continue

                    # Synchronous conflict resolution to prevent data loss.
                    base_filename = self._sanitize_filename(preferred_disk_name(file) or 'unknown')
                    filepath = base_path / base_filename
                    target_key = str(filepath).lower()

                    if target_key in seen_flat_paths:
                        counter = 1
                        while True:
                            new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                            new_filepath = base_path / new_name
                            if str(new_filepath).lower() not in seen_flat_paths:
                                filepath = new_filepath
                                target_key = str(new_filepath).lower()
                                break
                            counter += 1

                    seen_flat_paths.add(target_key)
                    try:
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, file, base_path, progress_callback, mb_tracker, file_filter,
                            error_root_path=error_root_path, course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath,
                            check_cancellation=check_cancellation
                        ))
                        tasks.append(task)
                    except Exception as e:
                        err = DownloadError(course.name, getattr(file, 'filename', 'unknown'), "Queue Error", str(e), raw_error=e)
                        if progress_callback: progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)
            except Exception as file_list_e:
                # File listing failed mid-iteration (e.g. 401, network drop).
                # Fall through to the module-scan fallback below. Debug-log only:
                # many courses simply restrict the Files tab for students (the
                # module scan then fetches everything), so surfacing this in the
                # live log alarmed users about a non-problem.
                log_debug(f"Files tab listing failed, falling back to module scan: {file_list_e}", debug_file)

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        err = DownloadError(course.name, "File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                        if progress_callback: progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)
                    elif result:
                        downloaded.append(result)

            # Module Scan Fallback
            module_tasks = []
            try:
                modules = course.get_modules()
                for module in modules:
                    if check_cancellation and check_cancellation(): break
                    items = list(module.get_module_items())
                    log_debug(f"Fallback Scan: Module {module.name} (found {len(items)} items)", debug_file)
                    for item in items:
                        if check_cancellation and check_cancellation(): break
                        
                        if item.type == 'File' and hasattr(item, 'content_id') and item.content_id in downloaded_ids: continue

                        try:
                            log_debug(f"  Fallback Item: {getattr(item, 'title', 'unknown')} (Type: {getattr(item, 'type', 'unknown')})", debug_file)
                            if item.type == 'File':
                                if not hasattr(item, 'content_id') or not item.content_id: continue
                                file_obj = course.get_file(item.content_id)
                                # Synchronous conflict resolution to prevent data loss
                                base_filename = self._sanitize_filename(preferred_disk_name(file_obj) or 'unknown')
                                filepath = base_path / base_filename
                                target_key = str(filepath).lower()

                                if target_key in seen_flat_paths:
                                    counter = 1
                                    while True:
                                        new_name = f"{filepath.stem} ({counter}){filepath.suffix}"
                                        new_filepath = base_path / new_name
                                        if str(new_filepath).lower() not in seen_flat_paths:
                                            filepath = new_filepath
                                            target_key = str(new_filepath).lower()
                                            break
                                        counter += 1

                                seen_flat_paths.add(target_key)
                                task = asyncio.create_task(self._download_file_async(
                                    sem, session, file_obj, base_path, progress_callback, mb_tracker, file_filter, 
                                    error_root_path=error_root_path, course_name=course.name, debug_file=debug_file,
                                    sync_manager=sync_manager, course_base_path=base_path, explicit_filepath=filepath
                                ))
                                module_tasks.append(task)
                            elif item.type == 'Page':
                                if not module_item_in_scope(item.type, file_filter): continue
                                if not hasattr(item, 'page_url') or not item.page_url: continue
                                page_obj = course.get_page(item.page_url)
                                page_id = getattr(page_obj, 'page_id', getattr(page_obj, 'id', 0))
                                filepath, _, _ = self._save_secondary_entity(
                                    'page', getattr(page_obj, 'title', 'Untitled Page'), getattr(page_obj, 'body', '') or '',
                                    base_path, course_base_path=base_path, sync_manager=sync_manager,
                                    canvas_entity_id=page_id, canvas_updated_at=getattr(page_obj, 'updated_at', '') or '',
                                    progress_callback=progress_callback, debug_file=debug_file, error_root_path=error_root_path,
                                    course_name=course.name, module_path=base_path, isolate=isolate_pages, has_attachments=False, metadata_pairs=[],
                                    content_sig=compute_entity_content_sig('page', page_obj)
                                )
                                if filepath and path_exists(filepath):
                                    info = CanvasFileInfo(
                                        id=-int(item.id) if hasattr(item, 'id') else 0,
                                        filename=filepath.name,
                                        display_name=getattr(page_obj, 'title', filepath.name),
                                        size=0,
                                        modified_at=getattr(page_obj, 'updated_at', datetime.now(timezone.utc).isoformat()),
                                        url=getattr(item, 'html_url', ''),
                                        content_type="text/html"
                                    )
                                    downloaded.append((info, filepath))
                            elif item.type in LINK_LIKE_MODULE_ITEM_TYPES:
                                if not module_item_in_scope(item.type, file_filter): continue
                                url = getattr(item, 'external_url', None)
                                if item.type == 'ExternalTool':
                                     url = getattr(item, 'html_url', None) or url
                                if url:
                                    filepath = self._create_link(item.title, url, base_path, progress_callback, error_root_path=error_root_path, course_name=course.name, debug_file=debug_file, sync_manager=sync_manager, course_base_path=base_path, canvas_item_id=-int(item.id) if hasattr(item, 'id') else 0, seen_paths=seen_flat_paths)
                                    if filepath and path_exists(filepath):
                                        info = CanvasFileInfo(
                                            id=-int(item.id) if hasattr(item, 'id') else 0,
                                            filename=filepath.name,
                                            display_name=item.title,
                                            size=0,
                                            modified_at=datetime.now(timezone.utc).isoformat(),
                                            url=url,
                                            content_type="application/x-url"
                                        )
                                        downloaded.append((info, filepath))
                        except Exception as e:
                             err = DownloadError(course.name, getattr(item, 'title', 'unknown'), "Fallback Scan Error", str(e), raw_error=e)
                             if progress_callback: progress_callback(err, progress_type='error')
                             self._log_error(error_root_path, err)
                             log_debug(f"Fallback scan item error: {getattr(item, 'title', 'unknown')}: {e}", debug_file)

                if module_tasks:
                   module_results = await asyncio.gather(*module_tasks, return_exceptions=True)
                   for result in module_results:
                       if isinstance(result, Exception):
                           err = DownloadError(course.name, "Fallback File Task", "Async Error", str(result), raw_error=result, is_app_error=True)
                           if progress_callback: progress_callback(err, progress_type='error')
                           self._log_error(error_root_path, err)
                       elif result:
                           downloaded.append(result)

            except Exception as e:
                err = DownloadError(course.name, "Fallback Module Scan", "Scan Error", str(e), raw_error=e, is_app_error=True)
                if progress_callback: progress_callback(err, progress_type='error')
                self._log_error(error_root_path, err)
                log_debug(f"Fallback module scan failed: {e}", debug_file)

        except Exception as e:
             err = DownloadError(course.name, "Flat Download", "Fatal Error", str(e), raw_error=e, is_app_error=True)
             if progress_callback: progress_callback(err, progress_type='error')
             self._log_error(error_root_path, err)
        
        return downloaded

    def _remember_placed_file(self, file_obj, filepath) -> None:
        """Note where this run put a Canvas file, and under WHICH manifest row.

        The row matters as much as the path: the same Canvas file is written
        under its true id by the Files tab and under a synthetic id by an
        isolate-mode attachment, and those two cases want opposite treatment
        (see :meth:`_claim_placed_copy`). Storing only the path would make the
        two indistinguishable at the point of decision.
        """
        raw_id = real_canvas_file_id(file_obj)
        if raw_id is None:
            return
        registry = getattr(self, '_file_registry', None)
        if registry is None:
            return  # not inside a course download (flat/legacy entry points)
        try:
            row_id = int(getattr(file_obj, 'id', 0) or 0)
        except (TypeError, ValueError):
            return
        registry[raw_id] = (row_id, Path(filepath))

    def _defer_to_canvas_content(self, file_obj, debug_file=None) -> bool:
        """True when a Files-tab sweep must yield this file to Canvas Content.

        Asked by the THREE loops that enumerate the Files tab - flat,
        folder-structure, and the modules-mode Catch-All. They ask it early,
        before reserving a filename, so a deferred file does not leave its name
        held against a later file that could legitimately use it.

        Every other caller is placing a file in its own right and must not ask.
        """
        placed = self._row_already_placed(int(getattr(file_obj, 'id', 0) or 0))
        if placed is None:
            return False
        log_debug(
            f"Files-tab sweep skipping Canvas Content attachment: "
            f"{getattr(file_obj, 'filename', '?')} "
            f"(ID: {getattr(file_obj, 'id', 0)}) -> {placed.name}", debug_file)
        return True

    def _row_already_placed(self, canvas_file_id):
        """Where this run put *canvas_file_id*'s file, if it owns that same row.

        The Catch-All's question, and the row half of it is the whole point.
        ``sync_manifest.canvas_file_id`` is the primary key, so an id that an
        earlier phase already wrote under has exactly one row and it is taken:
        a second copy could never be tracked, which is how the Files-tab copy
        came to be orphaned by the announcement's.

        Returns ``None`` when the file was placed under a DIFFERENT row - the
        isolate layout, where an attachment is re-keyed to a synthetic id. There
        the Files-tab entry is a separate tracked entity that genuinely deserves
        its own copy, so the caller must go ahead (and
        :meth:`_claim_placed_copy` will still serve it locally rather than
        fetching it twice).
        """
        placed = getattr(self, '_file_registry', {}).get(canvas_file_id)
        if placed is None:
            return None
        row_id, path = placed
        return path if row_id == canvas_file_id else None

    async def _claim_placed_copy(self, file_obj, dest, *, sync_manager,
                                 course_base_path, progress_callback,
                                 debug_file, file_size_bytes):
        """Place a file this run already fetched, instead of fetching it again.

        Canvas hands the SAME file to several phases, each of which computes
        its own destination: the module walk, the Files-tab Catch-All, and any
        Canvas Content attachment (announcement / assignment / quiz /
        discussion / submission). The Catch-All's skip set is built *before*
        the Canvas Content phase runs, so it cannot possibly know what that
        phase is about to claim - which is why one file was fetched twice, 21
        seconds apart, and landed as two copies under two different names.

        Reordering the phases was rejected: it would move the Canvas Content
        marker in the progress UI and, worse, change which phase claims a root
        filename first - renaming files in folders users already have. Instead
        the SECOND request is served from the copy already on disk.

        Two placements, decided by manifest identity rather than by preference:

        * **Shared row** (Mode A / ``isolate_secondary_content=False``, where the
          attachment keeps the file's true id) - **move**. The analyzer resolves
          that one id to the attachment's prefixed name, so the moved file is
          the only one the manifest can describe; leaving a second copy behind
          is what orphaned it. One fetch, one file, one row.
        * **Distinct rows** (Mode B / isolate, where the attachment is re-keyed
          to a synthetic id) - **copy**. Here the analyzer legitimately expects
          BOTH a Files-tab entry and an attachment entry, each with its own
          row. Moving would leave the Files-tab row pointing at nothing, and
          the next sync would re-download it to the root for ever. Two files as
          designed, but one fetch.

        Returns the usual ``(CanvasFileInfo, path)`` on success, or ``None`` to
        fall through to a normal download - which is what every failure does,
        so this can never make an outcome worse than not having tried.
        """
        raw_id = real_canvas_file_id(file_obj)
        registry = getattr(self, '_file_registry', None)
        if raw_id is None or not registry:
            return None
        placed = registry.get(raw_id)
        if placed is None:
            return None
        placed_row, src = placed
        try:
            src = Path(src)
            if src == Path(dest):
                return None  # already in place; the exists-check above handles it
            if not path_exists(src):
                registry.pop(raw_id, None)  # moved/deleted since - fetch it properly
                return None
            # Only ever claim within THIS course's folder. The registry lives on
            # the manager, which outlives a single course, and the retry entry
            # point (download_isolated_batch_async) does not build one - so a
            # stale entry could otherwise point at another course's file.
            if course_base_path is not None:
                src.relative_to(course_base_path)
        except (OSError, ValueError):
            return None

        # The decision is "does the copy we have already occupy the row we are
        # about to write" - NOT "is this id positive". Reading it off the id
        # would be wrong in exactly the case the phase order creates: the
        # Files-tab sweep asking for a file an isolate-mode attachment has
        # already placed would MOVE the attachment's copy out of its folder.
        shares_row = placed_row == int(getattr(file_obj, 'id', 0) or 0)
        verb = 'Moving' if shares_row else 'Copying'
        try:
            Path(make_long_path(dest.parent)).mkdir(parents=True, exist_ok=True)
            if shares_row:
                await asyncio.to_thread(
                    os.replace, make_long_path(src), make_long_path(dest))
                registry[raw_id] = (placed_row, dest)
            else:
                await asyncio.to_thread(
                    shutil.copy2, make_long_path(src), make_long_path(dest))
        except OSError as e:
            # Locked destination, cross-device, permissions - fall back to a
            # real download, which carries its own conflict handling.
            log_debug(f"Could not place already-downloaded file {src.name} "
                      f"-> {dest.name} ({e}); downloading it again.", debug_file)
            return None

        log_debug(f"{verb} already-downloaded file (ID: {raw_id}): "
                  f"{src.name} -> {dest}", debug_file)

        if sync_manager and course_base_path:
            try:
                rel_path = str(dest.relative_to(course_base_path)).replace('\\', '/')
                await asyncio.to_thread(
                    sync_manager.record_downloaded_file,
                    canvas_file_id=getattr(file_obj, 'id', raw_id),
                    canvas_filename=getattr(file_obj, 'filename', ''),
                    local_path=rel_path,
                    canvas_updated_at=getattr(file_obj, 'modified_at', None) or '',
                    original_size=getattr(file_obj, 'size', 0) or 0,
                    content_sig=getattr(file_obj, 'content_sig', '') or '',
                    clear_ignored=True,
                )
            except Exception as db_err:
                log_debug(f"Warning: DB record failed for placed copy {dest.name}: {db_err}",
                          debug_file)

        if progress_callback:
            # 'skipped', not 'download': the item IS delivered and must be
            # counted (and must reach the run ledger, which is what scopes
            # post-processing), but no bytes crossed the network - so its size
            # has to leave the MB denominator or the counter can never reach
            # its own total.
            progress_callback(dest.name, progress_type='skipped',
                              file_size=file_size_bytes,
                              explicit_filepath=str(dest))

        return (
            CanvasFileInfo(
                id=getattr(file_obj, 'id', raw_id),
                filename=getattr(file_obj, 'filename', ''),
                display_name=getattr(file_obj, 'display_name', getattr(file_obj, 'filename', '')),
                size=getattr(file_obj, 'size', 0),
                modified_at=getattr(file_obj, 'modified_at', None),
                md5=getattr(file_obj, 'md5', None),
                url=getattr(file_obj, 'url', ''),
                content_type=getattr(file_obj, 'content-type', ''),
                folder_id=getattr(file_obj, 'folder_id', None),
            ), dest
        )

    async def _download_file_async(self, sem, session, file_obj, folder_path, progress_callback, mb_tracker=None, file_filter='all', error_root_path=None, course_name="Unknown", debug_file=None, sync_manager=None, course_base_path=None, explicit_filepath=None, check_cancellation=None):
        if explicit_filepath:
            filepath = explicit_filepath
            filename = filepath.name
        else:
            filename = self._sanitize_filename(preferred_disk_name(file_obj) or 'unknown')
            filepath = folder_path / filename

        # OUT OF SCOPE, and that is not the same as IGNORED. This used to write an
        # `is_ignored` row for every file the filter dropped, so that a later sync
        # would not resurface it as new - a crutch for the analyzer, which did not
        # apply the filter at all. It made a scope decision look like a per-file
        # decision the user had taken: the Ignored Files dialog listed 23 files in
        # a real folder and offered to restore them, and restoring one would have
        # pulled a file into a folder configured to exclude it.
        #
        # `analyze_course` now asks `file_in_scope` itself, so the row is
        # unnecessary; and `sync/analysis.py` had already reached the same verdict
        # for its own copy of this filter ("M-12: files a non-'all' filter drops
        # are SKIPPED, not ignored"). The download engine was the last place still
        # doing it. Nothing is written here now - the file is simply not part of
        # what this folder is for.
        if not file_in_scope(filepath, file_filter):
            return

        # We save the original filepath to serve as our concurrency lock target key.
        # This resolves the race where two threads competing for the same base name
        # evaluate the path before either starts downloading.
        original_filepath = filepath

        # Check duplication by size
        file_size_bytes = getattr(file_obj, 'size', 0) or 0

        # Max-file-size gate (opt-in, configured in the Settings dialog).
        # Files over the user-specified limit are counted as successful
        # skips rather than errors - they're an intentional user choice.
        max_bytes = getattr(self, '_max_file_size_bytes', None)
        if max_bytes and file_size_bytes > max_bytes:
            size_mb_display = file_size_bytes / (1024 * 1024)
            log_debug(
                f"Skipping {filename}: {size_mb_display:.1f} MB exceeds user limit of "
                f"{max_bytes / (1024 * 1024):.0f} MB.",
                debug_file,
            )
            # Register as ignored in the sync DB so future syncs
            # don't surface these files as "new".
            if sync_manager:
                try:
                    await asyncio.to_thread(
                        sync_manager.ignore_file,
                        file_obj.id,
                        getattr(file_obj, 'filename', ''),
                        file_size_bytes
                    )
                except Exception:
                    pass  # Non-fatal: don't break download for DB issues
            if progress_callback:
                progress_callback(
                    f"{filename} ({size_mb_display:.1f} MB)",
                    progress_type='size_skipped',
                    file_size=file_size_bytes,
                )
            return

        async with manage_download_lock(original_filepath):
            # Only run disk-conflict resolution when the caller hasn't already
            # resolved naming via seen_flat_paths / seen_target_paths.
            # Running this inside the lock eliminates the TOCTOU file conflict race.
            if not explicit_filepath:
                filepath = self._handle_conflict(filepath)
                filename = filepath.name
            # Re-check existence inside lock
            if path_exists(filepath):
                try:
                    # We only skip if size matches. If size differs, we overwrite (update).
                    if file_size_bytes > 0 and os.stat(make_long_path(filepath)).st_size == file_size_bytes:
                        log_debug(f"Skipping existing file: {filename}", debug_file)
                        # User Request: Remove skipped files from Total MB count (they don't need downloading)
                        if progress_callback:
                             progress_callback("", progress_type='skipped', file_size=file_size_bytes, explicit_filepath=str(filepath.resolve()))
                        # Sync Run #0: Record skipped-but-existing files to the DB
                        if sync_manager and course_base_path:
                            try:
                                rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                                await asyncio.to_thread(
                                    sync_manager.record_downloaded_file,
                                    canvas_file_id=file_obj.id,
                                    canvas_filename=getattr(file_obj, 'filename', ''),
                                    local_path=rel_path,
                                    canvas_updated_at=getattr(file_obj, 'modified_at', None) or '',
                                    original_size=file_size_bytes
                                )
                            except Exception:
                                pass  # Non-fatal: don't break download for DB issues
                        self._remember_placed_file(file_obj, filepath)
                        return (
                            CanvasFileInfo(
                                id=file_obj.id,
                                filename=getattr(file_obj, 'filename', ''),
                                display_name=getattr(file_obj, 'display_name', getattr(file_obj, 'filename', '')),
                                size=getattr(file_obj, 'size', 0),
                                modified_at=getattr(file_obj, 'modified_at', None),
                                md5=getattr(file_obj, 'md5', None),
                                url=getattr(file_obj, 'url', ''),
                                content_type=getattr(file_obj, 'content-type', ''),
                                folder_id=getattr(file_obj, 'folder_id', None)
                            ), filepath
                        ) # Skip
                    else:
                        # H-10: size mismatch means EITHER Canvas updated the
                        # file OR the user edited their local copy. Mirror the
                        # sync engine's "never overwrite your edits" guarantee:
                        # overwrite in place ONLY when the local bytes provably
                        # equal the original download (manifest md5 baseline).
                        # Edited or unverifiable copies are preserved - the
                        # fresh Canvas version lands as a _NewVersion sibling.
                        _pristine = False
                        if sync_manager is not None:
                            try:
                                _baseline = await asyncio.to_thread(
                                    sync_manager.get_manifest_baseline, file_obj.id)
                                if _baseline and _baseline[0]:
                                    from core.sync_manager import compute_local_md5 as _cmd5
                                    _local_hash = await asyncio.to_thread(_cmd5, filepath)
                                    _pristine = bool(_local_hash) and _local_hash == _baseline[0]
                            except Exception:
                                _pristine = False
                        if _pristine:
                            log_debug(
                                f"File exists but size mismatch (local copy is the pristine "
                                f"original). Canvas: {file_size_bytes}, Local: "
                                f"{os.stat(make_long_path(filepath)).st_size}. Overwriting in place.", debug_file)
                        else:
                            _diverted = self._handle_conflict(
                                filepath.parent / f"{filepath.stem}_NewVersion{filepath.suffix}")
                            # REDIRECT FIRST, announce second. These two lines used
                            # to sit AFTER the progress_callback, so anything the
                            # callback raised skipped the redirect and left
                            # `filepath` pointing at the user's edited copy - which
                            # the download below then overwrote. A UI callback is
                            # exactly the kind of thing that raises (the analysis
                            # hook threw NameError on every tick for months), and
                            # the outer handler swallowed it without a word. The
                            # commit to the safe path must not depend on the
                            # cosmetic step that follows it.
                            #
                            # Reordering means `filename` is already the NEW name
                            # by the time the message is built, so keep the old
                            # one - the sentence is about the file the user
                            # edited, not the one being written.
                            _original_name = filename
                            filepath = _diverted
                            filename = filepath.name
                            log_debug(
                                f"File exists with size mismatch and local edits (or no "
                                f"baseline to verify against). Preserving the local copy; "
                                f"downloading new version as: {_diverted.name}", debug_file)
                            if progress_callback:
                                progress_callback(
                                    f"'{_original_name}' was changed locally - new Canvas "
                                    f"version saved as '{_diverted.name}'",
                                    progress_type='log',
                                )
                except Exception as _exists_err:
                    # Swallowed so a odd stat/permission error cannot abort the
                    # whole file - but LOGGED, because everything above decides
                    # whether the user's EDITED copy is preserved or overwritten,
                    # and a silent failure here is indistinguishable from the
                    # protection having worked.
                    log_debug(
                        f"Existing-file handling failed for {filename}: "
                        f"{type(_exists_err).__name__}: {_exists_err}", debug_file)
                    logger.warning(
                        "Existing-file handling failed for %s; the local copy may "
                        "not have been diverted to _NewVersion", filename,
                        exc_info=True)

            # This run may already hold these exact bytes: the same Canvas file
            # reaches the engine once per phase that references it, and each
            # phase computes its own destination. Place the copy we have rather
            # than fetching it a second time. Deliberately AFTER the
            # exists-check above (which is the cheaper answer when the
            # destination is already correct) and BEFORE the URL check, so an
            # attachment whose URL Canvas has since stripped still lands.
            _claimed = await self._claim_placed_copy(
                file_obj, filepath, sync_manager=sync_manager,
                course_base_path=course_base_path,
                progress_callback=progress_callback, debug_file=debug_file,
                file_size_bytes=file_size_bytes)
            if _claimed is not None:
                return _claimed

            # Create lightweight dictionary for session state JSON serialization safety
            safe_file_dict = {
                'filename': getattr(file_obj, 'filename', ''),
                'id': getattr(file_obj, 'id', ''),
                'url': getattr(file_obj, 'url', ''),
                'size': getattr(file_obj, 'size', 0),
                'content-type': getattr(file_obj, 'content-type', ''),
                'display_name': getattr(file_obj, 'display_name', ''),
                'modified_at': getattr(file_obj, 'modified_at', None),
                'md5': getattr(file_obj, 'md5', None),
                'folder_id': getattr(file_obj, 'folder_id', None)
            }

            url = file_obj.url
            if not url:

                # Check for LTI/Media streams
                from shared.helpers import is_lti_stream_ext
                if is_lti_stream_ext(filepath.suffix):
                    err = DownloadError(course_name, filename, "LTI/Media Stream", "This video is streamed via a Canvas plugin (e.g., Panopto/Studio) and cannot be directly downloaded.", context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                elif getattr(file_obj, 'locked_for_user', False):
                    # Teacher-locked file (module-linked but locked in Files):
                    # Canvas strips the download URL for students, so no retry
                    # can ever succeed - not even a browser can fetch it. Mark
                    # permanent so it lands in "Cannot Be Downloaded" instead
                    # of taunting the user with a retry button. NOT auto-ignored:
                    # teachers often lock files only until the lecture date, so
                    # a later run may legitimately succeed.
                    _lock_reason = (getattr(file_obj, 'lock_explanation', '') or '').strip()
                    err = DownloadError(
                        course_name, filename, "Locked File",
                        "The teacher has locked this file on Canvas, so it cannot be "
                        "downloaded" + (f" ({_lock_reason.rstrip('.')})" if _lock_reason else "") + ".",
                        context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                    err.retry_exhausted = True
                else:
                    err = DownloadError(course_name, filename, "No URL", "File object has no URL", context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})

                if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                self._log_error(error_root_path, err)
                return

            # aiofiles is imported at module level; reference is used below

            for attempt in range(MAX_RETRIES):
                try:
                    # Early Cancellation Guard (API DoS fix)
                    if check_cancellation and check_cancellation():
                        return
                    
                    # Bytes written during THIS attempt - rolled back from
                    # mb_tracker if the attempt fails and is retried, so the
                    # MB dashboard never double-counts re-downloaded chunks.
                    _attempt_bytes = 0

                    # Request block inside semaphore
                    async with sem:
                        if attempt == 0 and progress_callback:
                            progress_callback(filename, progress_type='downloading_start')
                        log_debug(f"Requesting URL: {url} (Attempt {attempt+1})", debug_file)
                        async with session.get(url) as response:
                            if response.status in (403, 429, 503):
                                wait = parse_retry_after(
                                    response.headers.get('Retry-After', ''),
                                    RETRY_DELAY * (2 ** attempt))
                                raise ValueError(f"RATE_LIMIT:{wait}")
                            elif 500 <= response.status < 600:
                                raise ValueError(f"SERVER_ERROR:{response.status}")

                            log_debug(f"Response Status: {response.status} Content-Type: {response.headers.get('Content-Type', 'unknown')}", debug_file)
                            if response.status == 200:
                                # --- Content-Type Validation ---
                                # Guards against Canvas returning HTML error pages
                                # with a 200 status (common LMS failure mode).
                                resp_ct = (response.headers.get('Content-Type', '') or '').lower().split(';')[0].strip()
                                is_html_response = resp_ct == 'text/html'
                                expects_html = filepath.suffix.lower() in ('.html', '.htm')
                                if is_html_response and not expects_html and file_size_bytes > 0:
                                    raise ValueError(
                                        f"Content-Type mismatch: server returned 'text/html' "
                                        f"but expected a binary file ({filepath.suffix}). "
                                        f"This usually means Canvas returned an error page."
                                    )
                                # --- Atomic .part Pattern ---
                                part_path = filepath.parent / (filepath.name + '.part')
                                download_interrupted = False
                                
                                try:
                                    async with aiofiles.open(make_long_path(part_path), 'wb') as f:
                                        total_bytes = 0
                                        # Hash the bytes as they stream past so the
                                        # sync manifest gets an MD5 baseline without a
                                        # second full read of the file. Created fresh
                                        # per attempt (retries re-open this block), so
                                        # it always reflects exactly the bytes written.
                                        _dl_hasher = hashlib.md5()
                                        while True:
                                            # Instant cancel check INSIDE the chunk loop via decoupled callable
                                            if check_cancellation and check_cancellation():
                                                download_interrupted = True
                                                break

                                            chunk = await response.content.read(1024*1024)
                                            if not chunk: break
                                            await f.write(chunk)
                                            _dl_hasher.update(chunk)
                                            total_bytes += len(chunk)
                                            _attempt_bytes += len(chunk)

                                            if mb_tracker:
                                                mb_tracker['bytes_downloaded'] += len(chunk)
                                                if progress_callback:
                                                    mb_down = mb_tracker['bytes_downloaded'] / (1024 * 1024)
                                                    progress_callback("", progress_type='mb_progress', mb_downloaded=mb_down)
                                except BaseException as write_err:  # audit-ignore
                                    # BaseException (not Exception) so that Streamlit's
                                    # RerunException and asyncio's CancelledError - both
                                    # BaseException subclasses that abort the download
                                    # mid-chunk (e.g. a click during the run) - also
                                    # trigger .part cleanup instead of leaving orphans.
                                    # Safe: cleanup-only handler, ALWAYS re-raises below.
                                    download_interrupted = True
                                    # Clean up .part file on write error
                                    try:
                                        if Path(make_long_path(part_path)).exists():
                                            Path(make_long_path(part_path)).unlink()
                                    except OSError:
                                        pass
                                    raise write_err
                                
                                # Handle interrupted download: delete partial .part file
                                if download_interrupted:
                                    try:
                                        if Path(make_long_path(part_path)).exists():
                                            Path(make_long_path(part_path)).unlink()
                                            log_debug(f"Cancelled: deleted partial {part_path.name}", debug_file)
                                    except OSError:
                                        pass
                                    return  # Cancel - do not return file info
                                
                                # Verify download completeness BEFORE rename
                                if file_size_bytes > 0 and total_bytes != file_size_bytes:
                                    flexible_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4v']
                                    is_flexible_media = any(filename.lower().endswith(ext) for ext in flexible_extensions)
                                    
                                    if is_flexible_media and total_bytes > 0:
                                        log_debug(f"Soft Warning: {filename} size mismatch (Expected {file_size_bytes}, got {total_bytes}). Bypassing for media file.", debug_file)
                                    else:
                                        # Incomplete download - delete .part and raise
                                        try:
                                            if Path(make_long_path(part_path)).exists():
                                                Path(make_long_path(part_path)).unlink()
                                        except OSError:
                                            pass
                                        raise Exception(f"File system error: Download incomplete. Expected {file_size_bytes} bytes, got {total_bytes} bytes.")
                                
                                # 100% success: atomic rename .part → final path
                                try:
                                    os.replace(make_long_path(part_path), make_long_path(filepath))
                                except PermissionError:
                                    error_msg = f"Cannot overwrite file (it may be open in another program): {filepath}"
                                    log_debug(error_msg, debug_file)
                                    try:
                                        if Path(make_long_path(part_path)).exists():
                                            Path(make_long_path(part_path)).unlink()
                                    except OSError:
                                        pass
                                    raise RuntimeError(error_msg)

                                log_debug(f"File Saved: {filepath} ({total_bytes} bytes)", debug_file)

                                # A later phase asking for this same Canvas file
                                # gets this copy instead of a second fetch.
                                self._remember_placed_file(file_obj, filepath)

                                # --- Sync Run #0: Record to DB AFTER successful atomic rename ---
                                # This is the safety guard: only fully-downloaded files get recorded.
                                # Cancelled/partial .part files never reach this point.
                                if sync_manager and course_base_path:
                                    try:
                                        rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                                        await asyncio.to_thread(
                                            sync_manager.record_downloaded_file,
                                            canvas_file_id=file_obj.id,
                                            canvas_filename=getattr(file_obj, 'filename', ''),
                                            local_path=rel_path,
                                            canvas_updated_at=getattr(file_obj, 'modified_at', None) or '',
                                            original_size=getattr(file_obj, 'size', 0),
                                            local_md5=_dl_hasher.hexdigest(),
                                            content_sig=getattr(file_obj, 'content_sig', '') or '',
                                            # Fresh bytes on disk: a stale is_ignored flag from a
                                            # past filter/size gate must not keep this file in the
                                            # Ignored bucket (skip-existing records preserve it).
                                            clear_ignored=True,
                                        )
                                    except Exception as db_err:
                                        log_debug(f"Warning: DB record failed for {filename}: {db_err}", debug_file)
                                        # Non-fatal: download succeeded, DB write failed. File is on disk.
                                
                                if progress_callback:
                                    progress_callback(f'Downloading file: {filename}', progress_type='download', explicit_filepath=str(filepath.resolve()))
                                    
                                return (
                                    CanvasFileInfo(
                                        id=file_obj.id,
                                        filename=getattr(file_obj, 'filename', ''),
                                        display_name=getattr(file_obj, 'display_name', getattr(file_obj, 'filename', '')),
                                        size=getattr(file_obj, 'size', 0),
                                        modified_at=getattr(file_obj, 'modified_at', None),
                                        md5=getattr(file_obj, 'md5', None),
                                        url=getattr(file_obj, 'url', ''),
                                        content_type=getattr(file_obj, 'content-type', ''),
                                        folder_id=getattr(file_obj, 'folder_id', None)
                                    ), filepath
                                )
                            else:
                                err_msg = f"Download failed with status {response.status}"
                                log_debug(f"ERROR: {err_msg}", debug_file)
                                err = DownloadError(course_name, filename, f"HTTP {response.status}", err_msg, context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                                if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                                self._log_error(error_root_path, err)
                                return

                except aiohttp.ClientConnectorCertificateError as e:
                    # MUST precede the ValueError clause: this exception also
                    # inherits ssl.CertificateError -> ValueError, so the
                    # generic ValueError handler below would otherwise catch
                    # and re-raise it out of the task (seen on macOS frozen
                    # builds: every file surfaced as one opaque "Async Error"
                    # with no retry accounting). TLS verification failures are
                    # permanent for this run - the trust store won't change
                    # between retries - so fail fast with an actionable,
                    # per-file error instead.
                    if mb_tracker and _attempt_bytes:
                        mb_tracker['bytes_downloaded'] = max(0, mb_tracker['bytes_downloaded'] - _attempt_bytes)
                    log_debug(f"SSL ERROR (permanent, no retry): {filename}: {e}", debug_file)
                    err = DownloadError(
                        course_name, filename, "SSL Certificate Error",
                        f"Secure connection to Canvas could not be verified: {e}",
                        raw_error=e,
                        context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter}
                    )
                    if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                    self._log_error(error_root_path, err)
                    return

                except ValueError as ve:
                    msg = str(ve)
                    if msg.startswith("RATE_LIMIT:"):
                        # float(), not int(): parse_retry_after returns a float,
                        # and int("2.0") raises ValueError - which this very
                        # handler would then re-raise as an opaque failure.
                        try:
                            wait_time = float(msg.split(":", 1)[1])
                        except (ValueError, IndexError):
                            wait_time = RETRY_DELAY * (2 ** attempt)
                        log_debug(f"Rate limited (403/429). Sleeping {wait_time}s outside semaphore.", debug_file)
                        # Cancel-aware sleep: poll the cancel flag every second
                        # instead of blocking for the full Retry-After. Without
                        # this a long rate-limit can hold up cancellation for
                        # minutes.
                        for _ in range(max(1, int(wait_time))):
                            if check_cancellation and check_cancellation():
                                return
                            await asyncio.sleep(1)
                        continue
                    elif msg.startswith("SERVER_ERROR:"):
                        backoff = RETRY_DELAY * (2 ** attempt)
                        for _ in range(max(1, int(backoff))):
                            if check_cancellation and check_cancellation():
                                return
                            await asyncio.sleep(1)
                        continue
                    raise ve
                    
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    # Roll back this attempt's partial bytes so the retry
                    # doesn't double-count them in the MB dashboard.
                    if mb_tracker and _attempt_bytes:
                        mb_tracker['bytes_downloaded'] = max(0, mb_tracker['bytes_downloaded'] - _attempt_bytes)
                    # TLS verification failures are permanent for this run -
                    # the trust store won't change between retries, so fail
                    # fast with an actionable message instead of burning the
                    # full retry/backoff budget on every single file.
                    if isinstance(e, aiohttp.ClientConnectorCertificateError) or 'CERTIFICATE_VERIFY_FAILED' in str(e):
                        log_debug(f"SSL ERROR (permanent, no retry): {filename}: {e}", debug_file)
                        err = DownloadError(
                            course_name, filename, "SSL Certificate Error",
                            f"Secure connection to Canvas could not be verified: {e}",
                            raw_error=e,
                            context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter}
                        )
                        if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                        self._log_error(error_root_path, err)
                        return
                    if attempt < MAX_RETRIES - 1:
                        # Cancel-aware backoff sleep so a hung connection
                        # can be aborted within ~1s of clicking Cancel.
                        backoff = RETRY_DELAY * (2 ** attempt)
                        for _ in range(max(1, int(backoff))):
                            if check_cancellation and check_cancellation():
                                return
                            await asyncio.sleep(1)
                    else:
                        err = DownloadError(course_name, filename, "Network Error", f"Max retries exceeded: {e}", raw_error=e, context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                        if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                        self._log_error(error_root_path, err)
                        return
                except Exception as e:
                    err = DownloadError(course_name, filename, "Write Error", f"File system error: {e}", raw_error=e, context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter})
                    if progress_callback: progress_callback(err, progress_type='error', file_size=file_size_bytes)
                    self._log_error(error_root_path, err)
                    return

            else:
                err = DownloadError(
                    course_name, filename, "Rate Limit/Server Exhausted",
                    f"Failed to download after {MAX_RETRIES} attempts due to repeated rate limits or server errors.",
                    context={'file_dict': safe_file_dict, 'filepath': str(filepath), 'file_filter': file_filter}
                )
                if progress_callback:
                    progress_callback(err, progress_type='error', file_size=file_size_bytes)
                self._log_error(error_root_path, err)
                return

    # ═══════════════════════════════════════════════════════════════
    # SECONDARY CONTENT ENGINE
    # ═══════════════════════════════════════════════════════════════

    # --- Routing Helpers --------------------------------------------------

    def _resolve_secondary_path(self, entity_type, entity_name, base_path,
                                module_path=None, isolate=True,
                                has_attachments=False):
        """Resolve the target directory and clean/prefixed filename.

        Mode A (isolate=False):
            Uses *module_path* (or course root if flat) and prepends a
            ``"Type: "`` prefix to avoid ambiguity among study files.

        Mode B (isolate=True):
            Creates ``base_path/<Category>/`` and, if the entity has
            attachments, an additional ``<Entity Name>/`` subfolder.

        Returns:
            ``(target_dir: Path, display_name: str)``
        """
        routing = _ENTITY_ROUTING[entity_type]
        safe_name = self._sanitize_filename(entity_name)

        if isolate:
            category_folder = base_path / routing['folder']
            if has_attachments:
                entity_folder = category_folder / safe_name
                Path(make_long_path(entity_folder)).mkdir(parents=True, exist_ok=True)
                return entity_folder, safe_name
            else:
                Path(make_long_path(category_folder)).mkdir(parents=True, exist_ok=True)
                return category_folder, safe_name
        else:
            target_dir = module_path if module_path else base_path
            Path(make_long_path(target_dir)).mkdir(parents=True, exist_ok=True)
            prefixed_name = f"{routing['prefix']}: {safe_name}"
            return target_dir, prefixed_name

    @staticmethod
    def _build_entity_html(title, body_html, metadata_pairs=None):
        """Build a complete HTML document from a title, HTML body, and metadata.

        Parameters
        ----------
        title : str
            Entity title (will be escaped).
        body_html : str | None
            Raw HTML content from Canvas (may be None for empty entities).
        metadata_pairs : list[tuple[str, str]] | None
            ``[(label, value), ...]`` rendered as a header block.
        """
        safe_title = html.escape(title)
        
        # Build the metadata block if provided
        meta_section = ""
        if metadata_pairs:
            formatted_items = []
            for k, v in metadata_pairs:
                if not v:
                    continue
                v_str = str(v)
                # Auto-detect and format ISO 8601 strings from Canvas
                if v_str.endswith('Z') and 'T' in v_str and len(v_str) >= 19:
                    v_str = _format_canvas_date(v_str)
                
                # Render URLs as clickable links
                if v_str.startswith('http://') or v_str.startswith('https://'):
                    v_html = f'<a href="{html.escape(v_str)}" target="_blank">{html.escape(v_str)}</a>'
                else:
                    v_html = html.escape(v_str)
                
                formatted_items.append(
                    f'<div class="meta-item"><span class="meta-label">{html.escape(str(k))}:</span> <span class="meta-value">{v_html}</span></div>'
                )
            
            if formatted_items:
                meta_section = f'<div class="meta-box">{"".join(formatted_items)}</div>'

        # Inject modern styling with 60% layout parity.
        # NOTE: this is the palette of the EXPORTED HTML DOCUMENT - a light theme
        # the user opens in a browser - not the app's dark UI. It is deliberately
        # NOT built from shared/theme.py, and Rule 8 is suppressed for it below:
        # matching an exported page to the app's dark tokens would be wrong.
        css = """
        <style>
            :root {
                /* # audit-ignore - exported-document light theme, not app tokens */
                --bg-canvas: #f9fafb;
                --bg-card: #ffffff;
                --text-main: #374151;
                --text-heading: #111827;
                --text-muted: #6b7280;
                --border-color: #e5e7eb;
                --accent-color: #3b82f6;
                --meta-bg: #f3f4f6;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
                line-height: 1.6;
                color: var(--text-main);
                background-color: var(--bg-canvas);
                margin: 0;
                padding: 0;
            }
            .container {
                width: 60%;
                margin: 3rem auto;
                background-color: var(--bg-card);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
                border-radius: 8px;
                padding: 40px 50px;
                box-sizing: border-box;
            }
            @media (max-width: 1200px) {
                .container { width: 80%; }
            }
            @media (max-width: 768px) {
                .container {
                    width: 95%;
                    padding: 25px 20px;
                    margin: 1.5rem auto;
                }
            }
            h1.doc-title {
                color: var(--text-heading);
                margin-top: 0;
                font-size: 2.2rem;
                line-height: 1.25;
                font-weight: 700;
                border-bottom: 2px solid var(--border-color);
                padding-bottom: 12px;
                margin-bottom: 25px;
            }
            .meta-box {
                background-color: var(--meta-bg);
                border-left: 4px solid var(--accent-color);
                padding: 16px 20px;
                margin-bottom: 30px;
                border-radius: 0 6px 6px 0;
                font-size: 0.95rem;
            }
            .meta-item {
                margin-bottom: 8px;
            }
            .meta-item:last-child {
                margin-bottom: 0;
            }
            .meta-label {
                font-weight: 600;
                color: var(--text-heading);
                display: inline-block;
                width: 160px;
            }
            .meta-value {
                color: var(--text-main);
            }
            .content-box {
                font-size: 1.05rem;
            }
            .content-box img {
                max-width: 100%;
                height: auto;
                border-radius: 6px;
                display: block;
                margin: 1.5rem 0;
            }
            .content-box table {
                border-collapse: collapse;
                width: 100%;
                margin: 1.5rem 0;
            }
            .content-box th, .content-box td {
                border: 1px solid var(--border-color);
                padding: 10px 14px;
                text-align: left;
            }
            .content-box th {
                background-color: var(--meta-bg);
                font-weight: 600;
            }
            .content-box a {
                color: var(--accent-color);
                text-decoration: none;
                word-break: break-word;
            }
            .content-box a:hover {
                text-decoration: underline;
            }
            .content-box blockquote {
                border-left: 4px solid var(--border-color);
                padding-left: 1.25rem;
                margin-left: 0;
                margin-right: 0;
                color: var(--text-muted);
                font-style: italic;
                background-color: rgba(243, 244, 246, 0.4);
                padding-top: 0.5rem;
                padding-bottom: 0.5rem;
                border-radius: 0 4px 4px 0;
            }
            .content-box pre {
                background-color: var(--meta-bg);
                padding: 1.25rem;
                border-radius: 6px;
                overflow-x: auto;
                font-size: 0.9rem;
            }
            .content-box code {
                background-color: var(--meta-bg);
                padding: 0.2rem 0.4rem;
                border-radius: 4px;
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
                font-size: 0.9em;
            }
            .content-box pre code {
                background-color: transparent;
                padding: 0;
            }
        </style>
        """

        html_out = (
            f"<!DOCTYPE html>\n"
            f"<html lang=\"en\">\n"
            f"<head>\n"
            f"<meta charset=\"utf-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
            f"<title>{safe_title}</title>\n"
            f"{css}\n"
            f"</head>\n"
            f"<body>\n"
            f"<div class=\"container\">\n"
            f"<h1 class=\"doc-title\">{safe_title}</h1>\n"
            f"{meta_section}\n"
            f"<div class=\"content-box\">\n"
            f"{body_html or '<p><em>(No content provided)</em></p>'}\n"
            f"</div>\n"
            f"</div>\n"
            f"</body>\n"
            f"</html>"
        )
        return html_out

    def _save_secondary_entity(self, entity_type, entity_name, body_html,
                               base_path, course_base_path, sync_manager,
                               canvas_entity_id, canvas_updated_at,
                               progress_callback=None, debug_file=None,
                               error_root_path=None, course_name="Unknown",
                               module_path=None, isolate=True,
                               has_attachments=False, metadata_pairs=None,
                               file_extension=".html", raw_body=False,
                               content_sig="", explicit_dir=None,
                               preserve_existing=False):
        """Unified save-to-disk + DB-record logic for all secondary entities.

        ``raw_body=True`` writes *body_html* verbatim (used for Markdown
        rubrics) instead of wrapping it in the HTML document template.

        ``content_sig`` (H-1): signature of the raw source fields, stamped
        into the manifest row so the analyzer can detect real content changes.

        ``explicit_dir`` (H-2): write into THIS directory instead of the
        canonical category/module layout - used by the sync update path to
        respect the folder the user moved the entity's file into.

        ``preserve_existing`` (H-1 + never-overwrite-edits): when True and the
        target exists, the fresh render is written as a ``_NewVersion``
        sibling instead of replacing the file - used for updates of entities
        whose local copy the user edited.

        Returns
        -------
        ``(filepath, synthetic_id, canvas_updated_at)`` on success, ``(None, None, None)`` on failure.
        """
        if explicit_dir is not None:
            # H-2: honour the directory the user's copy actually lives in.
            # The filename shape (bare name in Mode B, "Type: name" in Mode A)
            # is derived directly so the canonical category/module folders are
            # NOT created as a side effect. Falls back to the canonical layout
            # only if the explicit directory cannot be created.
            _routing = _ENTITY_ROUTING[entity_type]
            _safe = self._sanitize_filename(entity_name)
            display_name = _safe if isolate else f"{_routing['prefix']}: {_safe}"
            target_dir = Path(explicit_dir)
            try:
                Path(make_long_path(target_dir)).mkdir(parents=True, exist_ok=True)
            except OSError:
                target_dir, display_name = self._resolve_secondary_path(
                    entity_type, entity_name, base_path,
                    module_path=module_path, isolate=isolate,
                    has_attachments=has_attachments,
                )
        else:
            target_dir, display_name = self._resolve_secondary_path(
                entity_type, entity_name, base_path,
                module_path=module_path, isolate=isolate,
                has_attachments=has_attachments,
            )

        filename = self._sanitize_filename(display_name) + file_extension
        filepath = target_dir / filename

        # Same-name collision guard: two DISTINCT entities (different Canvas
        # IDs) can sanitize to the same filename - e.g. duplicate assignment
        # titles. The per-run registry detects this and suffixes the later
        # one instead of silently overwriting the first. Re-saves of the SAME
        # entity within a run keep overwriting in place as designed.
        _registry = getattr(self, '_sec_registry', None)
        if _registry is not None:
            _reg_key = str(filepath).lower()
            _owner = _registry.get(_reg_key)
            if _owner is not None and _owner != (entity_type, canvas_entity_id):
                filepath = self._handle_conflict(filepath)
            _registry[str(filepath).lower()] = (entity_type, canvas_entity_id)

        if preserve_existing and path_exists(filepath):
            # The user edited their local copy: never touch it. The fresh
            # render lands alongside as a _NewVersion sibling (mirroring the
            # regular-file modified-update routing).
            filepath = self._handle_conflict(
                filepath.parent / f"{filepath.stem}_NewVersion{filepath.suffix}"
            )
        elif path_exists(filepath):
            # Secondary entities are always regenerated from the Canvas API,
            # so overwrite in-place instead of creating (1) conflict copies.
            # This mirrors the clean-overwrite logic for regular file redownloads.
            try:
                Path(make_long_path(filepath)).unlink()
            except OSError:
                # File locked (e.g. open in browser) - fall back to conflict copy
                filepath = self._handle_conflict(filepath)

        content = body_html if raw_body else self._build_entity_html(
            entity_name, body_html, metadata_pairs=metadata_pairs,
        )

        log_debug(f"Saving {entity_type}: {entity_name} -> {filepath}", debug_file)

        part_path = filepath.with_suffix(filepath.suffix + '.part')
        try:
            with open(make_long_path(part_path), 'w', encoding='utf-8') as f:
                f.write(content)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(make_long_path(part_path), make_long_path(filepath))
        except Exception as e:
            try:
                Path(make_long_path(part_path)).unlink(missing_ok=True)
            except OSError:
                pass
            err = DownloadError(
                course_name, entity_name,
                f"{entity_type.title()} Save Error", str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            return None, None, None  # callers unpack (filepath, syn_id, canvas_updated)

        # DB record ― synthetic negative ID
        synthetic_id = make_secondary_id(entity_type, canvas_entity_id)

        # Record in the sync manifest so subsequent syncs don't re-download this
        # entity. This is centralised here so every call-site is automatically
        # correct - including the module-dispatch loop which only calls
        # _save_secondary_entity and discards the return value.
        if sync_manager and filepath:
            try:
                rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                sync_manager.record_downloaded_file(
                    canvas_file_id=synthetic_id,
                    canvas_filename=filepath.name,
                    local_path=rel_path,
                    canvas_updated_at=canvas_updated_at or '',
                    original_size=0,
                    content_sig=content_sig or '',
                    clear_ignored=True,  # fresh bytes were just written
                )
            except Exception as _db_err:
                log_debug(f"DB record failed for {entity_type} '{entity_name}': {_db_err}", debug_file)

        if progress_callback:
            progress_callback(
                entity_name, progress_type='secondary',
                entity_type=entity_type, explicit_filepath=str(filepath)
            )

        return filepath, synthetic_id, canvas_updated_at or ''

    def download_secondary_entity(self, course, canvas_file_info, base_path,
                                   sync_manager, secondary_content_settings,
                                   progress_callback=None, debug_file=None,
                                   error_root_path=None, course_name="Unknown",
                                   module_path=None, explicit_dir=None,
                                   preserve_existing=False):
        """Fetch a single secondary entity from Canvas and save it to disk.

        This is the UNIVERSAL entry point used by both:
          - The initial download pipeline (via _download_secondary_content)
          - The sync download loop (sync_ui.py)

        Parameters
        ----------
        course : canvasapi.Course
            The Canvas course object.
        canvas_file_info : CanvasFileInfo
            Must have a negative ``.id`` in the SECONDARY_ID_OFFSETS range.
        base_path : Path
            Course root folder on disk.
        sync_manager : SyncManager
            For DB recording.
        secondary_content_settings : dict
            The active secondary content contract.
        module_path : Path | None
            Mode A only: target module subfolder. When ``isolate=False``
            and the entity is module-linked, this is the absolute path of
            the module folder where the entity should be written. The sync
            engine derives this from the analyzer's ``target_local_path``.
            Mode B (``isolate=True``) ignores this argument entirely.
        explicit_dir : Path | None
            H-2: when set, write into THIS directory (where the user's copy
            lives) instead of the canonical category/module layout.
        preserve_existing : bool
            H-1: when True and the target exists (user-edited local copy),
            the regenerated entity is written as a ``_NewVersion`` sibling.

        Returns
        -------
        ``(filepath: Path | None, synthetic_id: int | None, attachments: list | None)``
        Where ``attachments`` is a list of Canvas attachment dicts (each with
        ``id``, ``url``, ``filename``, ``size``) - only populated for assignments.
        """
        # Local imports to prevent circular dependency with sync_manager
        from core.sync_manager import (
            SECONDARY_ID_OFFSETS, is_secondary_id, secondary_id_type,
        )

        file_id = canvas_file_info.id
        if not is_secondary_id(file_id):
            return None, None, None, None

        entity_type = secondary_id_type(file_id)
        if not entity_type or entity_type in ('module_item', 'unknown'):
            return None, None, None, None

        isolate = secondary_content_settings.get('isolate_secondary_content', True)
        offset = SECONDARY_ID_OFFSETS.get(entity_type, 0)
        raw_id = abs(file_id) - offset

        try:
            if entity_type == 'assignment':
                assignment = course.get_assignment(raw_id)

                # Extract attachments BEFORE saving the HTML body
                attachments = []
                try:
                    raw_att = getattr(assignment, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                # ── Inline-link extraction (HTML body) ──
                # Instructors embed file links in the description HTML.
                # These are NOT in the attachments API field.
                a_desc = getattr(assignment, 'description', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(a_desc):
                    # H-5: cancel check so a 50-link description doesn't block cancel
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue  # Already captured via API attachments
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Due', getattr(assignment, 'due_at', None)),
                    ('Points', getattr(assignment, 'points_possible', None)),
                    ('Submission Types', ', '.join(
                        getattr(assignment, 'submission_types', []) or []
                    )),
                    ('URL', getattr(assignment, 'html_url', None)),
                ]
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'assignment',
                    getattr(assignment, 'name', 'Untitled Assignment'),
                    assignment_body_html(course, assignment, a_desc, debug_file),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(assignment, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                    content_sig=compute_entity_content_sig('assignment', assignment),
                    explicit_dir=explicit_dir,
                    preserve_existing=preserve_existing,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'quiz':
                quiz = course.get_quiz(raw_id)
                
                attachments = []
                try:
                    raw_att = getattr(quiz, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                q_desc = getattr(quiz, 'description', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(q_desc):
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Points', getattr(quiz, 'points_possible', None)),
                    ('Due', getattr(quiz, 'due_at', None)),
                    ('URL', getattr(quiz, 'html_url', None)),
                ]
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'quiz',
                    getattr(quiz, 'title', 'Untitled Quiz'),
                    quiz_body_html(quiz, debug_file),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(quiz, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                    content_sig=compute_entity_content_sig('quiz', quiz),
                    explicit_dir=explicit_dir,
                    preserve_existing=preserve_existing,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'discussion':
                topic = resolve_discussion_topic(course, raw_id, debug_file)
                
                attachments = []
                try:
                    raw_att = getattr(topic, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                t_msg = getattr(topic, 'message', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(t_msg):
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Posted', getattr(topic, 'posted_at', None)),
                    ('Replies', getattr(topic, 'discussion_subentry_count', None)),
                    ('URL', getattr(topic, 'html_url', None)),
                ]
                updated_at = (getattr(topic, 'last_reply_at', '')
                              or getattr(topic, 'updated_at', '') or '')
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'discussion',
                    getattr(topic, 'title', 'Untitled Discussion'),
                    t_msg + self._build_discussion_replies_html_sync(topic, debug_file),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                    content_sig=compute_entity_content_sig('discussion', topic),
                    explicit_dir=explicit_dir,
                    preserve_existing=preserve_existing,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'announcement':
                topic = resolve_discussion_topic(course, raw_id, debug_file)
                
                attachments = []
                try:
                    raw_att = getattr(topic, 'attachments', None)
                    if raw_att and isinstance(raw_att, list):
                        attachments = raw_att
                except Exception:
                    pass

                t_msg = getattr(topic, 'message', '') or ''
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(t_msg):
                    try:
                        from core.cancellation import is_sync_cancelled, is_download_cancelled
                        if is_sync_cancelled() or is_download_cancelled():
                            break
                    except Exception:
                        pass
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                metadata = [
                    ('Posted', getattr(topic, 'posted_at', None)),
                    ('URL', getattr(topic, 'html_url', None)),
                ]

                # Date-prefix for chronological file ordering (parity with
                # _fetch_and_save_announcements and get_secondary_content_metadata)
                posted_at = getattr(topic, 'posted_at', '') or ''
                date_prefix = ''
                if posted_at:
                    try:
                        dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
                        date_prefix = dt.strftime('%Y-%m-%d') + ' - '
                    except (ValueError, TypeError):
                        pass
                _ann_display = f"{date_prefix}{getattr(topic, 'title', 'Announcement')}"

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'announcement',
                    _ann_display,
                    t_msg + self._build_discussion_replies_html_sync(topic, debug_file),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(topic, 'posted_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=bool(attachments),
                    metadata_pairs=metadata,
                    content_sig=compute_entity_content_sig('announcement', topic),
                    explicit_dir=explicit_dir,
                    preserve_existing=preserve_existing,
                )
                return filepath, syn_id, attachments or None, canvas_updated

            elif entity_type == 'syllabus':
                full_course = self.canvas.get_course(
                    course.id, include=['syllabus_body'],
                )
                body = getattr(full_course, 'syllabus_body', '') or ''
                if not body:
                    return None, None, None, None
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'syllabus', 'Syllabus', body,
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=course.id,
                    canvas_updated_at=getattr(full_course, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=False,
                    metadata_pairs=None,
                    content_sig=compute_entity_content_sig('syllabus', body),
                    explicit_dir=explicit_dir,
                    preserve_existing=preserve_existing,
                )
                return filepath, syn_id, None, canvas_updated

            elif entity_type == 'rubric':
                rubric = course.get_rubric(raw_id)
                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'rubric',
                    getattr(rubric, 'title', 'Rubric'),
                    _build_rubric_markdown(rubric),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=raw_id,
                    canvas_updated_at=getattr(rubric, 'updated_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course_name, isolate=isolate,
                    module_path=module_path,
                    has_attachments=False,
                    metadata_pairs=None,
                    file_extension='.md',
                    raw_body=True,
                    content_sig=compute_entity_content_sig('rubric', rubric),
                    explicit_dir=explicit_dir,
                    preserve_existing=preserve_existing,
                )
                return filepath, syn_id, None, canvas_updated

            else:
                log_debug(f"Unknown secondary entity type: {entity_type} for ID {file_id}", debug_file)
                return None, None, None, None  # callers unpack (filepath, syn_id, attachments, canvas_updated)

        except Exception as e:
            log_debug(f"Failed to download secondary entity {entity_type} (ID {file_id}): {e}", debug_file)
            raise  # Let exceptions bubble up so the sync retry loop can handle them

    # --- Entity-Specific Fetchers -----------------------------------------

    def _build_discussion_replies_html_sync(self, topic, debug_file=None):
        """Fetch and format discussion/announcement replies synchronously."""
        from canvasapi.exceptions import Unauthorized, ResourceDoesNotExist
        from shared.helpers import esc
        from core.canvas_debug import log_debug
        
        try:
            entries = list(topic.get_topic_entries())
            if not entries:
                return ""
            
            html_out = ["<hr style='margin-top: 30px; border: 0; border-top: 1px solid #e4e4e7;'><h3 style='margin-bottom: 20px; color: #3f3f46;'>Replies</h3>"]
            
            def render_entry(entry, depth=0):
                margin = min(depth * 30, 150)
                author = getattr(entry, 'user_name', 'Unknown Author')
                message = getattr(entry, 'message', '') or ''
                created_at = getattr(entry, 'created_at', '')
                
                formatted_date = _format_canvas_date(created_at) if created_at else ""
                
                # Exported-document (light) palette, not the app's dark tokens.  # audit-ignore
                html_out.append(f"<div style='margin-left: {margin}px; padding: 15px; margin-bottom: 12px; background-color: #f4f4f5; border-left: 3px solid #3b82f6; border-radius: 4px;'>")
                html_out.append(f"<div style='margin-bottom: 8px;'><strong>{esc(author)}</strong> <span style='color: #71717a; font-size: 0.9em; margin-left: 8px;'>{esc(formatted_date)}</span></div>")
                
                att_list = []
                raw_atts = getattr(entry, 'attachments', [])
                if not raw_atts:
                    single_att = getattr(entry, 'attachment', None)
                    if single_att:
                        raw_atts = [single_att]
                        
                for att in raw_atts:
                    url = att.get('url', '')
                    display_name = att.get('display_name') or att.get('filename') or 'attachment'
                    if url:
                        att_list.append(f"<a href='{esc(url)}' target='_blank' style='color: #3b82f6; text-decoration: none;'>📎 {esc(display_name)}</a>")
                
                attachments_html = ""
                if att_list:
                    attachments_html = "<div style='margin-top: 10px; padding-top: 10px; border-top: 1px dashed #d4d4d8; font-size: 0.9em;'>" + "<br>".join(att_list) + "</div>"

                html_out.append(f"<div style='color: #27272a; margin-top: 8px;'>{message}</div>")
                html_out.append(attachments_html)
                
                if hasattr(entry, 'get_replies'):
                    if depth >= _DISCUSSION_MAX_REPLY_DEPTH:
                        # Say what is being hidden rather than truncating in
                        # silence - the export is the user's only copy of this
                        # thread.
                        html_out.append(
                            "<div style='color: #71717a; font-size: 0.9em;'>"
                            "<em>Further nested replies were not exported "
                            "(maximum reply depth reached).</em></div>")
                        if debug_file:
                            log_debug(
                                f"Discussion reply depth cap "
                                f"({_DISCUSSION_MAX_REPLY_DEPTH}) reached; "
                                "deeper replies skipped.", debug_file)
                    else:
                        try:
                            for sub_entry in entry.get_replies():
                                # A reply graph that came back cyclic would
                                # otherwise recurse until RecursionError, which
                                # the outer handler swallows into an empty
                                # Replies section. Mirrors the `seen` set that
                                # guards the Panopto subfolder walk.
                                _sub_id = getattr(sub_entry, 'id', None)
                                if _sub_id is not None:
                                    if _sub_id in _seen_entry_ids:
                                        continue
                                    _seen_entry_ids.add(_sub_id)
                                render_entry(sub_entry, depth + 1)
                        except Exception as e:
                            if debug_file:
                                log_debug(f"Could not fetch sub-replies: {e}", debug_file)
                html_out.append("</div>")

            _seen_entry_ids: set = set()
            for entry in entries:
                _eid = getattr(entry, 'id', None)
                if _eid is not None:
                    if _eid in _seen_entry_ids:
                        continue
                    _seen_entry_ids.add(_eid)
                render_entry(entry, 0)
                
            return "\n".join(html_out)
        except (Unauthorized, ResourceDoesNotExist):
            return "<hr style='margin-top: 30px; border: 0; border-top: 1px solid #e4e4e7;'><p style='color: #71717a;'><em>Replies could not be accessed.</em></p>"
        except Exception as e:
            if debug_file:
                from core.canvas_debug import log_debug
                log_debug(f"Error fetching replies: {e}", debug_file)
            return ""

    def _fetch_and_save_assignments(self, course, base_path, sem, session,
                                    progress_callback, mb_tracker,
                                    check_cancellation, settings,
                                    error_root_path, debug_file,
                                    sync_manager, module_handled_ids,
                                    download_tasks):
        """Fetch all assignments for a course and save their HTML bodies.

        Attachments on Canvas Assignments are real Canvas File objects
        ― they are queued for async download using their *true positive*
        ``file.id``, just like any normal course file.
        """
        from core.sync_manager import make_secondary_id
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching assignments...", debug_file)

        try:
            # List API with a module-item fallback so a restricted assignment
            # list doesn't silently drop module-embedded assignments (same sync
            # asymmetry as quizzes - see _enumerate_module_backed).
            assignments = self._enumerate_module_backed(
                course, debug_file, label='Assignment',
                list_getter=course.get_assignments, item_type='Assignment',
                individual_getter=course.get_assignment,
            )
            for assignment in assignments:
                if check_cancellation and check_cancellation():
                    break

                a_id = getattr(assignment, 'id', 0)
                if a_id in module_handled_ids:
                    continue  # Already saved via module dispatch

                a_name = getattr(assignment, 'name', 'Untitled Assignment')
                description = getattr(assignment, 'description', '') or ''
                updated_at = getattr(assignment, 'updated_at', '') or ''

                # Signature source: prefer the richer individually-fetched
                # object; the list stub is the fallback when the refetch fails.
                _sig_obj = assignment

                # Check for file attachments
                # IMPORTANT: course.get_assignments() (list endpoint) does NOT
                # return the `attachments` field. We must refetch each
                # assignment individually to get full data including attached
                # files - this mirrors the sync path's download_secondary_entity.
                attachments = []
                try:
                    full_assignment = course.get_assignment(a_id)
                    _sig_obj = full_assignment
                    # Update description/updated_at from the richer individual response
                    description = getattr(full_assignment, 'description', '') or description
                    updated_at = getattr(full_assignment, 'updated_at', '') or updated_at
                    raw_attachments = getattr(full_assignment, 'attachments', None)
                    if raw_attachments and isinstance(raw_attachments, list):
                        attachments = raw_attachments
                        log_debug(f"  Assignment '{a_name}': found {len(attachments)} API attachment(s)", debug_file)
                except Exception as att_err:
                    log_debug(f"  Could not refetch assignment {a_id} for attachments: {att_err}", debug_file)

                # ── Inline-link extraction (HTML body) ──
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(description):
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                has_attachments = bool(attachments)
                if has_attachments:
                    log_debug(f"  Assignment '{a_name}': {len(attachments)} total attachment(s) (API + inline)", debug_file)

                metadata = [
                    ('Due', getattr(assignment, 'due_at', None)),
                    ('Points', getattr(assignment, 'points_possible', None)),
                    ('Submission Types', ', '.join(
                        getattr(assignment, 'submission_types', []) or []
                    )),
                    ('URL', getattr(assignment, 'html_url', None)),
                ]

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'assignment', a_name,
                    # _sig_obj, not `assignment`: it is the richer refetched
                    # object where one was obtained, and the list stub only as
                    # fallback - the same preference the signature above makes.
                    assignment_body_html(course, _sig_obj, description, debug_file),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=a_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    has_attachments=has_attachments,
                    metadata_pairs=metadata,
                    content_sig=compute_entity_content_sig('assignment', _sig_obj),
                )

                # CRITICAL: Save the parent HTML file to the database manifest
                if filepath and sync_manager:
                    try:
                        from pathlib import Path
                        rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=Path(filepath).name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception as e:
                        print(f"CRITICAL DB ERROR: {e}")

                # Queue attachment downloads using their REAL positive IDs
                if filepath and attachments:
                    attach_dir = filepath.parent
                    for att in attachments:
                        raw_id = att.get('id')
                        att_url = att.get('url', '')
                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                        if not att_url or not raw_id:
                            continue

                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        if not isolate:
                            # Mode A: prefix attachment filename
                            routing = _ENTITY_ROUTING['assignment']
                            att_filename = f"{routing['prefix']}: {self._sanitize_filename(a_name)} - {att_filename}"

                        # Build a mock file object that _download_file_async expects
                        att_file_obj = types.SimpleNamespace(
                            id=att_id,
                            url=att_url,
                            filename=att_filename,
                            display_name=att.get('display_name', att_filename),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', updated_at),
                            md5=None,
                            content_type=att.get('content-type', ''),
                            folder_id=None,
                            name_locked=True,
                        )

                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                        if progress_callback:
                            progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))
                        
                        task = asyncio.create_task(self._download_file_async(
                            sem, session, att_file_obj, attach_dir,
                            progress_callback, mb_tracker, 'attachment',
                            error_root_path=error_root_path,
                            course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager,
                            course_base_path=base_path,
                            explicit_filepath=att_filepath,
                        ))
                        download_tasks.append(task)

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Assignments not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Assignments", "Canvas Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_syllabus(self, course, base_path,
                                 progress_callback, settings,
                                 error_root_path, debug_file,
                                 sync_manager):
        """Fetch the course syllabus_body and save as a single HTML file."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching syllabus...", debug_file)

        try:
            # Re-fetch the course object with syllabus_body included
            full_course = self.canvas.get_course(
                course.id, include=['syllabus_body'],
            )
            syllabus_body = getattr(full_course, 'syllabus_body', None)

            if not syllabus_body:
                log_debug("Syllabus body is empty, skipping.", debug_file)
                return

            updated_at = getattr(full_course, 'updated_at', '') or ''

            filepath, syn_id, canvas_updated = self._save_secondary_entity(
                'syllabus', 'Syllabus', syllabus_body, base_path,
                course_base_path=base_path, sync_manager=sync_manager,
                canvas_entity_id=course.id, canvas_updated_at=updated_at,
                progress_callback=progress_callback,
                debug_file=debug_file,
                error_root_path=error_root_path,
                course_name=course.name, isolate=isolate,
                content_sig=compute_entity_content_sig('syllabus', syllabus_body),
                has_attachments=False,
                metadata_pairs=[
                    ('Course', getattr(course, 'name', '')),
                    ('Course Code', getattr(full_course, 'course_code', '')),
                    ('URL', getattr(full_course, 'html_url', None) or getattr(course, 'html_url', None)),
                ],
            )
            
            if filepath and sync_manager:
                try:
                    rel_path = str(filepath.relative_to(base_path)).replace('\\', '/')
                    sync_manager.record_downloaded_file(
                        canvas_file_id=syn_id,
                        canvas_filename=filepath.name,
                        local_path=rel_path,
                        canvas_updated_at=canvas_updated,
                        original_size=0,
                    )
                except Exception:
                    pass

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Syllabus not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Syllabus", "Canvas Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_announcements(self, course, base_path, sem, session,
                                      progress_callback, mb_tracker,
                                      check_cancellation, settings,
                                      error_root_path, debug_file,
                                      sync_manager, download_tasks):
        """Fetch course announcements and save each as an HTML file.

        Attachments on announcements are real Canvas File objects and are
        queued for download using their true positive IDs.
        """
        from core.sync_manager import make_secondary_id
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching announcements...", debug_file)

        try:
            topics = course.get_discussion_topics(only_announcements=True)
            for topic in topics:
                if check_cancellation and check_cancellation():
                    break

                t_id = getattr(topic, 'id', 0)
                title = getattr(topic, 'title', 'Untitled Announcement')
                message = getattr(topic, 'message', '') or ''
                posted_at = getattr(topic, 'posted_at', '') or ''
                updated_at = posted_at  # Announcements rarely get edited

                # Date-prefix for chronological file ordering
                date_prefix = ''
                if posted_at:
                    try:
                        dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
                        date_prefix = dt.strftime('%Y-%m-%d') + ' - '
                    except (ValueError, TypeError):
                        pass

                # Check for attachments
                attachments = []
                try:
                    raw = getattr(topic, 'attachments', None)
                    if raw and isinstance(raw, list):
                        attachments = raw
                except Exception:
                    pass

                # ── Inline-link extraction (HTML body) ──
                # Mirrors the assignments saver AND the sync-analysis
                # enumerator (get_course_files_metadata): files linked in the
                # announcement body are real Canvas files that sync analysis
                # counts as attachment entities. Without downloading them here,
                # every fresh download was immediately followed by a sync that
                # reported them as phantom "new" files (seen 2026-06-11:
                # 'G7-Assignment-1.pdf', 'Late Lecture with DHH Slide.pdf').
                existing_att_ids = {a.get('id') for a in attachments if isinstance(a, dict)}
                for link_info in _extract_canvas_file_links(message):
                    fid = link_info['file_id']
                    if fid in existing_att_ids:
                        continue
                    log_debug(f"    Inline link: fetching metadata for file {fid} ('{link_info['link_text']}')...", debug_file)
                    try:
                        canvas_file = course.get_file(fid)
                        attachments.append({
                            'id': canvas_file.id,
                            'url': canvas_file.url,
                            'filename': getattr(canvas_file, 'filename', link_info['link_text']),
                            'display_name': getattr(canvas_file, 'display_name', link_info['link_text']),
                            'size': getattr(canvas_file, 'size', 0),
                            'modified_at': getattr(canvas_file, 'modified_at', ''),
                            'content-type': getattr(canvas_file, 'content_type', ''),
                        })
                        existing_att_ids.add(canvas_file.id)
                    except (Unauthorized, ResourceDoesNotExist):
                        log_debug(f"    Inline link: file {fid} is inaccessible or deleted - skipping", debug_file)
                    except Exception as e:
                        log_debug(f"    Inline link: error fetching file {fid}: {e}", debug_file)

                has_attachments = bool(attachments)
                display_name = f"{date_prefix}{title}"

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'announcement', display_name, message + self._build_discussion_replies_html_sync(topic, debug_file), base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=t_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    content_sig=compute_entity_content_sig('announcement', topic),
                    has_attachments=has_attachments,
                    metadata_pairs=[
                        ('Posted', posted_at),
                        ('Author', getattr(topic, 'user_name', None)
                                   or getattr(topic, 'author', {}).get('display_name', None)),
                        ('URL', getattr(topic, 'html_url', None)),
                    ],
                )

                # CRITICAL: Save the parent HTML file to the database manifest
                if filepath and sync_manager:
                    try:
                        from pathlib import Path
                        rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=Path(filepath).name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception as e:
                        print(f"CRITICAL DB ERROR: {e}")

                # Queue attachment downloads with REAL positive IDs
                if filepath and attachments:
                    attach_dir = filepath.parent
                    for att in attachments:
                        raw_id = att.get('id')
                        att_url = att.get('url', '')
                        att_filename = att.get('filename', att.get('display_name', 'attachment'))
                        if not att_url or not raw_id:
                            continue

                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id

                        if not isolate:
                            routing = _ENTITY_ROUTING['announcement']
                            att_filename = f"{routing['prefix']}: {self._sanitize_filename(display_name)} - {att_filename}"

                        att_file_obj = types.SimpleNamespace(
                            id=att_id,
                            url=att_url,
                            filename=att_filename,
                            display_name=att.get('display_name', att_filename),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', updated_at),
                            md5=None,
                            content_type=att.get('content-type', ''),
                            folder_id=None,
                            name_locked=True,
                        )

                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                        if progress_callback:
                            progress_callback(att_filename, progress_type='attachment_discovered', size=att.get('size', 0))

                        task = asyncio.create_task(self._download_file_async(
                            sem, session, att_file_obj, attach_dir,
                            progress_callback, mb_tracker, 'attachment',
                            error_root_path=error_root_path,
                            course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager,
                            course_base_path=base_path,
                            explicit_filepath=att_filepath,
                        ))
                        download_tasks.append(task)

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Announcements not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Announcements", "Canvas Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_submissions_with_feedback(self, course, debug_file):
        """Return this student's submissions that carry feedback.

        One bulk call for the whole course, with a per-assignment fallback.
        ``GET /courses/:id/students/submissions?student_ids[]=self`` is the cheap
        path (one paginated request regardless of assignment count), but some
        Canvas instances restrict it for student tokens - in which case we fall
        back to asking each assignment for its own submission. Never raises.
        """
        include = ['submission_comments', 'rubric_assessment', 'assignment']
        subs = []
        try:
            for sub in course.get_multiple_submissions(
                    student_ids=['self'], include=include):
                subs.append(sub)
            log_debug(f"Secondary: bulk submissions fetch returned {len(subs)}", debug_file)
        except Exception as e:
            log_debug(f"Secondary: bulk submissions fetch failed ({e}); "
                      f"falling back to per-assignment", debug_file)
            subs = []
            try:
                for assignment in course.get_assignments():
                    try:
                        sub = assignment.get_submission('self', include=include)
                    except (Unauthorized, ResourceDoesNotExist):
                        continue
                    except Exception as inner:
                        log_debug(f"    submission for assignment "
                                  f"{getattr(assignment, 'id', '?')}: {inner}", debug_file)
                        continue
                    # The per-assignment endpoint does not always inline the
                    # assignment, so attach it for the title/points below.
                    if getattr(sub, 'assignment', None) is None:
                        try:
                            sub.assignment = {
                                'id': assignment.id,
                                'name': getattr(assignment, 'name', ''),
                                'points_possible': getattr(assignment, 'points_possible', None),
                                'html_url': getattr(assignment, 'html_url', ''),
                            }
                        except Exception:
                            pass
                    subs.append(sub)
            except Exception as outer:
                log_debug(f"Secondary: per-assignment submission fallback failed: {outer}",
                          debug_file)
                return []

        return [s for s in subs if _submission_has_feedback(s)]

    @staticmethod
    def _submission_assignment_field(sub, field, default=None):
        """Read a field off a submission's inlined assignment (dict or object)."""
        a = getattr(sub, 'assignment', None)
        if a is None:
            return default
        if isinstance(a, dict):
            return a.get(field, default)
        return getattr(a, field, default)

    def _build_submission_feedback_html(self, sub) -> str:
        """Render the rubric assessment and the comment thread as HTML."""
        parts = []

        rubric = getattr(sub, 'rubric_assessment', None) or {}
        if isinstance(rubric, dict) and rubric:
            rows = []
            for crit_id, val in rubric.items():
                val = val or {}
                pts = val.get('points')
                comment = str(val.get('comments') or '').strip()
                rows.append(
                    '<tr>'
                    f'<td>{html.escape(str(crit_id))}</td>'
                    f'<td>{html.escape("" if pts is None else str(pts))}</td>'
                    f'<td>{html.escape(comment)}</td>'
                    '</tr>'
                )
            if rows:
                parts.append(
                    '<h3>Rubric assessment</h3>'
                    '<table border="1" cellpadding="6" cellspacing="0">'
                    '<tr><th>Criterion</th><th>Points</th><th>Comment</th></tr>'
                    + ''.join(rows) + '</table>'
                )

        comments = getattr(sub, 'submission_comments', None) or []
        rendered = []
        for c in comments:
            text = str(_comment_field(c, 'comment') or '').strip()
            if not text:
                continue
            author = _comment_field(c, 'author_name') or ''
            if not author:
                author_obj = _comment_field(c, 'author') or {}
                author = (author_obj.get('display_name')
                          if isinstance(author_obj, dict) else '') or 'Unknown'
            created = _format_canvas_date(_comment_field(c, 'created_at') or '')
            atts = _comment_field(c, 'attachments') or []
            att_note = ''
            if isinstance(atts, list) and atts:
                names = [html.escape(str((a.get('display_name') or a.get('filename'))
                                         if isinstance(a, dict)
                                         else getattr(a, 'display_name', '')) or '')
                         for a in atts]
                att_note = ('<div class="meta-item"><span class="meta-label">Attached:</span> '
                            f'<span class="meta-value">{", ".join(n for n in names if n)}'
                            '</span></div>')
            rendered.append(
                '<div class="reply">'
                f'<p><b>{html.escape(str(author))}</b>'
                f'{f" &middot; {html.escape(str(created))}" if created else ""}</p>'
                f'<p>{html.escape(text)}</p>'
                f'{att_note}'
                '</div>'
            )
        if rendered:
            parts.append('<h3>Comments</h3>' + ''.join(rendered))

        if not parts:
            # Graded with no rubric and no comments - the metadata block above
            # already carries the grade, so say so rather than render an empty page.
            parts.append('<p><i>Graded, with no rubric assessment or comments.</i></p>')
        return ''.join(parts)

    def _fetch_and_save_submissions(self, course, base_path, sem, session,
                                    progress_callback, mb_tracker,
                                    check_cancellation, settings,
                                    error_root_path, debug_file,
                                    sync_manager, download_tasks):
        """Save the FEEDBACK on this student's submissions - grade, rubric,
        comments - plus any files a teacher attached to a comment.

        Deliberately does NOT download the student's own submitted files: they
        already have those locally. Assignments with no feedback yet produce no
        file at all, so enabling this on a course that has never been graded is a
        silent no-op rather than a folder of "not graded yet" stubs.
        """
        from core.sync_manager import make_secondary_id
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching submission feedback...", debug_file)

        try:
            subs = self._fetch_submissions_with_feedback(course, debug_file)
            log_debug(f"Secondary: {len(subs)} submission(s) carry feedback", debug_file)

            for sub in subs:
                if check_cancellation and check_cancellation():
                    break

                s_id = _submission_entity_id(sub)
                if s_id is None:
                    # Must match get_secondary_content_metadata's skip exactly,
                    # or sync lists a file this never writes.
                    log_debug("Secondary: skipping submission with no resolvable "
                              "assignment id", debug_file)
                    continue
                a_name = (self._submission_assignment_field(sub, 'name')
                          or f"Assignment {s_id}").strip()
                points_possible = self._submission_assignment_field(sub, 'points_possible')
                a_url = self._submission_assignment_field(sub, 'html_url') or ''

                grade = getattr(sub, 'entered_grade', None) or getattr(sub, 'grade', None)
                score = getattr(sub, 'entered_score', None)
                if score is None:
                    score = getattr(sub, 'score', None)
                score_text = None
                if score is not None:
                    score_text = (f"{score} / {points_possible}"
                                  if points_possible is not None else str(score))

                status_bits = [getattr(sub, 'workflow_state', '') or '']
                if getattr(sub, 'late', False):
                    status_bits.append('late')
                if getattr(sub, 'missing', False):
                    status_bits.append('missing')
                if getattr(sub, 'excused', False):
                    status_bits.append('excused')
                status = ', '.join(b for b in status_bits if b)

                attachments = _submission_comment_attachments(sub)
                has_attachments = bool(attachments)

                body_html = self._build_submission_feedback_html(sub)

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'submission', a_name, body_html, base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=s_id,
                    canvas_updated_at=getattr(sub, 'graded_at', '') or '',
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    content_sig=compute_entity_content_sig('submission', sub),
                    has_attachments=has_attachments,
                    metadata_pairs=[
                        ('Assignment', a_name),
                        ('Grade', grade),
                        ('Score', score_text),
                        ('Status', status),
                        ('Graded', getattr(sub, 'graded_at', None)),
                        ('URL', a_url or None),
                    ],
                )

                if filepath and sync_manager:
                    try:
                        rel_path = str(Path(filepath).relative_to(Path(base_path))).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=Path(filepath).name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                            content_sig=compute_entity_content_sig('submission', sub),
                        )
                    except Exception as e:
                        logger.warning(f"Manifest write failed for submission feedback "
                                       f"'{a_name}': {e}")

                # Teacher comment attachments: real Canvas files with real ids.
                if filepath and attachments:
                    attach_dir = filepath.parent
                    for att in attachments:
                        raw_id = att.get('id')
                        att_url = att.get('url', '')
                        att_filename = att.get('filename') or 'attachment'
                        if not att_url or not raw_id:
                            continue

                        att_id = make_secondary_id('attachment', raw_id) if isolate else raw_id
                        if not isolate:
                            routing = _ENTITY_ROUTING['submission']
                            att_filename = (f"{routing['prefix']}: "
                                            f"{self._sanitize_filename(a_name)} - {att_filename}")

                        att_file_obj = types.SimpleNamespace(
                            id=att_id,
                            url=att_url,
                            filename=att_filename,
                            display_name=att.get('display_name', att_filename),
                            size=att.get('size', 0),
                            modified_at=att.get('modified_at', ''),
                            md5=None,
                            content_type=att.get('content-type', ''),
                            folder_id=None,
                            name_locked=True,
                        )
                        att_filepath = attach_dir / self._sanitize_filename(att_filename)
                        if progress_callback:
                            progress_callback(att_filename,
                                              progress_type='attachment_discovered',
                                              size=att.get('size', 0))
                        download_tasks.append(asyncio.create_task(self._download_file_async(
                            sem, session, att_file_obj, attach_dir,
                            progress_callback, mb_tracker, 'attachment',
                            error_root_path=error_root_path,
                            course_name=course.name, debug_file=debug_file,
                            sync_manager=sync_manager,
                            course_base_path=base_path,
                            explicit_filepath=att_filepath,
                        )))

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Submission feedback not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Submission Feedback", "Canvas Content Error",
                humanize_canvas_error(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_discussions(self, course, base_path,
                                    progress_callback, check_cancellation,
                                    settings, error_root_path, debug_file,
                                    sync_manager, module_handled_ids):
        """Fetch non-announcement discussion topics and save as HTML."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching discussions...", debug_file)

        try:
            # List API with a module-item fallback so a restricted discussion
            # list doesn't silently drop module-embedded discussions (same sync
            # asymmetry as quizzes - see _enumerate_module_backed).
            topics = self._enumerate_module_backed(
                course, debug_file, label='Discussion',
                list_getter=course.get_discussion_topics, item_type='Discussion',
                individual_getter=course.get_discussion_topic,
            )
            for topic in topics:
                if check_cancellation and check_cancellation():
                    break

                t_id = getattr(topic, 'id', 0)
                if t_id in module_handled_ids:
                    continue

                # Skip announcements (they have is_announcement=True)
                if getattr(topic, 'is_announcement', False):
                    continue

                title = getattr(topic, 'title', 'Untitled Discussion')
                message = getattr(topic, 'message', '') or ''
                updated_at = (getattr(topic, 'last_reply_at', '')
                              or getattr(topic, 'updated_at', '')
                              or '')

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'discussion', title, message + self._build_discussion_replies_html_sync(topic, debug_file), base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=t_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    content_sig=compute_entity_content_sig('discussion', topic),
                    has_attachments=False,
                    metadata_pairs=[
                        ('Posted', getattr(topic, 'posted_at', None)),
                        ('Replies', getattr(topic, 'discussion_subentry_count', None)),
                        ('Author', getattr(topic, 'user_name', None)
                                   or getattr(topic, 'author', {}).get('display_name', None)),
                        ('URL', getattr(topic, 'html_url', None)),
                    ],
                )
                
                if filepath and sync_manager:
                    try:
                        rel_path = str(filepath.relative_to(base_path)).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=filepath.name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception:
                        pass

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Discussions not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Discussions", "Canvas Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _enumerate_module_backed(self, course, debug_file, *, label,
                                 list_getter, item_type, individual_getter):
        """List-API-first enumeration with a module-item fallback.

        Used for the secondary entities (Assignment / Quiz / Discussion) that
        the sync analyzer reads DIRECTLY from module items
        (``_get_files_from_modules``) but a flat-mode download fetches via a
        per-type LIST endpoint. On locked-down institutional Canvas those LIST
        endpoints frequently 403/404 while the *individual* GET stays
        accessible - so a flat download would silently drop the module-embedded
        entity, and the next sync would then flag it as a phantom "N new files"
        immediately after a fresh download.

        Preferred path: ``list_getter()`` (e.g. ``course.get_quizzes``).
        Fallback (only when that raises): walk modules, and for every item of
        ``item_type`` fetch it individually via ``individual_getter(content_id)``
        (e.g. ``course.get_quiz``). The IDs line up because a module item's
        ``content_id`` equals the entity's ``id``, so the synthetic manifest ID
        (``make_secondary_id(type, id)``) matches on both the download and sync
        sides and the entry is recognised rather than re-flagged as new.

        This only changes the SOURCE of the objects; the caller's existing
        per-entity processing, ``module_handled_ids`` dedup (which prevents
        double-handling in modules mode), and ID generation are untouched.
        """
        try:
            return list(list_getter())
        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(
                f"{label} list endpoint restricted ({e}); falling back to "
                f"module-embedded {label.lower()}s.", debug_file
            )

        out = []
        seen = set()
        try:
            for module in course.get_modules():
                try:
                    items = module.get_module_items()
                except Exception:
                    continue
                for item in items:
                    if getattr(item, 'type', '') != item_type:
                        continue
                    cid = getattr(item, 'content_id', 0) or 0
                    if not cid or cid in seen:
                        continue
                    seen.add(cid)
                    try:
                        out.append(individual_getter(cid))
                    except Exception as ie:
                        log_debug(
                            f"Module-embedded {label.lower()} {cid} not "
                            f"individually fetchable: {ie}", debug_file
                        )
        except Exception as me:
            log_debug(f"Module-{label.lower()} fallback enumeration failed: {me}", debug_file)
        return out

    def _fetch_and_save_quizzes(self, course, base_path,
                                progress_callback, check_cancellation,
                                settings, error_root_path, debug_file,
                                sync_manager, module_handled_ids):
        """Fetch Classic Quizzes and serialise questions into structured HTML."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching quizzes...", debug_file)

        try:
            # List API with a module-item fallback so a restricted quiz list
            # doesn't silently drop module-embedded quizzes (see
            # _enumerate_module_backed - fixes the "1 new file after a fresh
            # download" sync asymmetry for locked-down courses).
            quizzes = self._enumerate_module_backed(
                course, debug_file, label='Quiz',
                list_getter=course.get_quizzes, item_type='Quiz',
                individual_getter=course.get_quiz,
            )
            for quiz in quizzes:
                if check_cancellation and check_cancellation():
                    break

                q_id = getattr(quiz, 'id', 0)
                if q_id in module_handled_ids:
                    continue

                q_title = getattr(quiz, 'title', 'Untitled Quiz')
                q_description = getattr(quiz, 'description', '') or ''
                updated_at = getattr(quiz, 'updated_at', '') or ''

                # One implementation, shared with every other quiz save site -
                # see quiz_body_html. This used to be the ONLY place questions
                # were fetched at all, so a quiz reached any other way was saved
                # with an empty body and rendered as "(No content provided)".
                full_body = quiz_body_html(quiz, debug_file)

                filepath, syn_id, canvas_updated = self._save_secondary_entity(
                    'quiz', q_title, full_body, base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=q_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    content_sig=compute_entity_content_sig('quiz', quiz),
                    has_attachments=False,
                    metadata_pairs=[
                        ('Points', getattr(quiz, 'points_possible', None)),
                        # None when unset → the metadata builder omits the row
                        # entirely (previously rendered as "None min").
                        ('Time Limit', f"{getattr(quiz, 'time_limit', None)} min" if getattr(quiz, 'time_limit', None) else None),
                        ('Due', getattr(quiz, 'due_at', None)),
                        ('Allowed Attempts', getattr(quiz, 'allowed_attempts', None)),
                        ('URL', getattr(quiz, 'html_url', None)),
                    ],
                )
                
                if filepath and sync_manager:
                    try:
                        rel_path = str(filepath.relative_to(base_path)).replace('\\', '/')
                        sync_manager.record_downloaded_file(
                            canvas_file_id=syn_id,
                            canvas_filename=filepath.name,
                            local_path=rel_path,
                            canvas_updated_at=canvas_updated,
                            original_size=0,
                        )
                    except Exception:
                        pass

        except (Unauthorized, ResourceDoesNotExist) as e:
            log_debug(f"Quizzes not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Quizzes", "Canvas Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    def _fetch_and_save_rubrics(self, course, base_path,
                                progress_callback, check_cancellation,
                                settings, error_root_path, debug_file,
                                sync_manager):
        """Fetch rubrics and serialise as Markdown tables."""
        isolate = settings.get('isolate_secondary_content', True)
        log_debug("Secondary: Fetching rubrics...", debug_file)

        try:
            rubrics = course.get_rubrics()
            for rubric in rubrics:
                if check_cancellation and check_cancellation():
                    break

                r_id = getattr(rubric, 'id', 0)
                r_title = getattr(rubric, 'title', 'Untitled Rubric')
                updated_at = getattr(rubric, 'updated_at', '') or ''

                # Unified writer: shared Markdown builder + overwrite-in-place
                # semantics + same-name registry + manifest record. Replaces
                # the old inline writer which used _handle_conflict and thus
                # accumulated "Rubric (1).md" duplicates on every re-download.
                self._save_secondary_entity(
                    'rubric', r_title, _build_rubric_markdown(rubric),
                    base_path,
                    course_base_path=base_path, sync_manager=sync_manager,
                    canvas_entity_id=r_id, canvas_updated_at=updated_at,
                    progress_callback=progress_callback,
                    debug_file=debug_file,
                    error_root_path=error_root_path,
                    course_name=course.name, isolate=isolate,
                    has_attachments=False,
                    metadata_pairs=None,
                    file_extension='.md',
                    raw_body=True,
                    content_sig=compute_entity_content_sig('rubric', rubric),
                )

        except (Unauthorized, ResourceDoesNotExist, CanvasException) as e:
            log_debug(f"Rubrics not accessible: {e}", debug_file)
        except Exception as e:
            err = DownloadError(
                course.name, "Rubrics", "Canvas Content Error",
                str(e), raw_error=e,
            )
            if progress_callback:
                progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)

    # --- Orchestrator ------------------------------------------------------

    async def _download_secondary_content(self, course, base_path, sem,
                                           session, progress_callback,
                                           mb_tracker, check_cancellation,
                                           settings, error_root_path,
                                           debug_file, sync_manager,
                                           module_handled_ids):
        """Download all secondary entities based on the settings dict.

        Called from ``download_course_async()`` AFTER file downloads complete.
        ``module_handled_ids`` contains entity IDs already processed during
        the module-item loop so they are not downloaded twice.

        Attachment download tasks are gathered at the end.
        """
        if not settings:
            return
        log_debug("=== Starting Canvas Content Download ===", debug_file)

        if progress_callback:
            progress_callback(
                'Downloading Course Pages & Assignments...',
                progress_type='phase',
                phase_name='Canvas Content',
            )

        download_tasks = []  # Async tasks for attachment downloads

        def _sec_category(label, fn, *args):
            """Run ONE secondary-content category, absorbing what it raises.

            The seven categories below are independent - a malformed quiz says
            nothing about the user's submissions - but they were seven bare
            calls in a row, so the FIRST one to raise silently skipped every
            category after it. The user asked for quizzes + submissions +
            rubrics and got one generic "Canvas Content Error" with no way to
            tell which of them actually ran.

            Reported per category, so the error names the part that failed.
            """
            try:
                fn(*args)
                return True
            except Exception as _cat_err:
                log_debug(f"Canvas Content: {label} failed: "
                          f"{type(_cat_err).__name__}: {_cat_err}", debug_file)
                logger.warning("Secondary-content category %s failed", label,
                               exc_info=True)
                err = DownloadError(
                    course.name, f"Canvas Content: {label}",
                    "Canvas Content Error", str(_cat_err),
                    raw_error=_cat_err, is_app_error=True,
                )
                if progress_callback:
                    progress_callback(err, progress_type='error')
                self._log_error(error_root_path, err)
                return False

        try:
            # 1. Assignments
            if settings.get('download_assignments'):
                _sec_category('assignments', self._fetch_and_save_assignments,
                    course, base_path, sem, session,
                    progress_callback, mb_tracker, check_cancellation,
                    settings, error_root_path, debug_file,
                    sync_manager, module_handled_ids, download_tasks)

            # 2. Syllabus
            if settings.get('download_syllabus'):
                _sec_category('syllabus', self._fetch_and_save_syllabus,
                    course, base_path, progress_callback, settings,
                    error_root_path, debug_file, sync_manager)

            # 3. Announcements
            if settings.get('download_announcements'):
                _sec_category('announcements', self._fetch_and_save_announcements,
                    course, base_path, sem, session,
                    progress_callback, mb_tracker, check_cancellation,
                    settings, error_root_path, debug_file,
                    sync_manager, download_tasks)

            # 4. Discussions
            if settings.get('download_discussions'):
                _sec_category('discussions', self._fetch_and_save_discussions,
                    course, base_path, progress_callback,
                    check_cancellation, settings,
                    error_root_path, debug_file,
                    sync_manager, module_handled_ids)

            # 5. Quizzes
            if settings.get('download_quizzes'):
                _sec_category('quizzes', self._fetch_and_save_quizzes,
                    course, base_path, progress_callback,
                    check_cancellation, settings,
                    error_root_path, debug_file,
                    sync_manager, module_handled_ids)

            # 6. Submission feedback (grade, rubric, teacher comments + their files).
            #    NOT the student's own uploads - see _fetch_and_save_submissions.
            if settings.get('download_submissions'):
                _sec_category('submissions', self._fetch_and_save_submissions,
                    course, base_path, sem, session,
                    progress_callback, mb_tracker, check_cancellation,
                    settings, error_root_path, debug_file,
                    sync_manager, download_tasks)

            # 7. Rubrics (temporarily disabled via RUBRICS_ENABLED - see flag definition)
            if RUBRICS_ENABLED and settings.get('download_rubrics'):
                _sec_category('rubrics', self._fetch_and_save_rubrics,
                    course, base_path, progress_callback,
                    check_cancellation, settings,
                    error_root_path, debug_file, sync_manager)
        finally:
            # Gather all attachment download tasks.
            #
            # In a `finally` because these are already-scheduled
            # asyncio.create_task() coroutines: anything raising above would
            # skip the gather, asyncio.run() would cancel them at loop close,
            # and every attachment assignments/announcements had queued would
            # vanish - reported as nothing more specific than one generic
            # Canvas Content error. Awaiting them is what makes the work
            # already in flight survive a failure in a LATER category.
            if download_tasks:
                log_debug(f"Waiting for {len(download_tasks)} attachment downloads...", debug_file)
                results = await asyncio.gather(*download_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        err = DownloadError(
                            course.name, "Attachment Task", "Async Error",
                            str(result), raw_error=result,
                        )
                        if progress_callback:
                            progress_callback(err, progress_type='error')
                        self._log_error(error_root_path, err)

        log_debug("=== Canvas Content Download Complete ===", debug_file)

    def _create_link(self, title, url, folder_path, progress_callback, error_root_path=None, course_name="Unknown", debug_file=None, sync_manager=None, course_base_path=None, canvas_item_id=0, seen_paths=None):
        """Write a .url/.webloc shortcut for an external link.

        Overwrites a same-named shortcut from a PREVIOUS run in place (links
        are fully regenerated from Canvas, so numbered "(1)" copies would
        just pile up on every re-download). ``seen_paths`` - the caller's
        per-run path set - still disambiguates two DIFFERENT links that
        sanitize to the same title within a single run.
        """
        import plistlib
        safe_title = self._sanitize_filename(title)

        ext = ".webloc" if platform.system() == 'Darwin' else ".url"
        filepath = folder_path / f"{safe_title}{ext}"

        if seen_paths is not None:
            if str(filepath).lower() in seen_paths:
                # Same-run duplicate title → numbered sibling
                filepath = self._handle_conflict(filepath)
            seen_paths.add(str(filepath).lower())

        if progress_callback:
            progress_callback(f'Creating link: {title}', progress_type='link', explicit_filepath=str(filepath))

        log_debug(f"Creating Link: {title} ({url}) -> {filepath}", debug_file)

        try:
            if platform.system() == 'Darwin':
                # Binary-safe plist generation - plistlib handles all XML
                # escaping internally, making manual saxutils.escape() unnecessary.
                content = plistlib.dumps({'URL': url}, fmt=plistlib.FMT_XML)
                with open(make_long_path(filepath), 'wb') as f:
                    f.write(content)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            else:
                safe_url = url.replace('\r', '').replace('\n', '')
                content = f'[InternetShortcut]\nURL={safe_url}'
                with open(make_long_path(filepath), 'w', encoding='utf-8') as f:
                    f.write(content)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            # Sync Run #0: Record link/URL file to DB using deterministic canvas_item_id
            if sync_manager and course_base_path and canvas_item_id:
                try:
                    rel_path = str(filepath.relative_to(course_base_path)).replace('\\', '/')
                    sync_manager.record_downloaded_file(
                        canvas_file_id=canvas_item_id,
                        canvas_filename=filepath.name,
                        local_path=rel_path,
                        canvas_updated_at=datetime.now(timezone.utc).isoformat(),
                        original_size=0,
                        content_sig=link_content_sig(title, url),
                        clear_ignored=True,
                    )
                except Exception:
                    pass  # Non-fatal
            return filepath
        except Exception as e:
            err = DownloadError(course_name, title, "Link Creation Error", str(e), raw_error=e)
            if progress_callback: progress_callback(err, progress_type='error')
            self._log_error(error_root_path, err)
            import logging
            logging.getLogger(__name__).error(f"Error creating link: {e}")
            log_debug(f"Error creating link: {e}", debug_file)
            return None

    def _handle_conflict(self, filepath):
        if not path_exists(filepath):
            return filepath
        base = filepath.stem
        ext = filepath.suffix
        parent = filepath.parent
        counter = 1
        while path_exists(filepath) and counter < 1000:
            new_name = f"{base} ({counter}){ext}"
            filepath = parent / new_name
            counter += 1
        if counter >= 1000:
            for _ in range(100):
                candidate = parent / f"{base}_{uuid.uuid4().hex[:8]}{ext}"
                if not path_exists(candidate):
                    filepath = candidate
                    break
            else:
                import logging as _log
                _log.getLogger(__name__).warning(
                    f"_handle_conflict: could not find a free name for {base}{ext} after UUID fallback"
                )
        return filepath

    def _sanitize_filename(self, filename, replace_spaces=False, max_length=120):
        if not filename: return "untitled"
        # Normalize to NFC and strip dangerous Unicode characters:
        # - Bidirectional overrides (e.g. U+202E Right-to-Left Override)
        # - Zero-width spaces and joiners
        # - BOM
        filename = unicodedata.normalize('NFC', filename)
        _DANGEROUS_UNICODE = (
            '‮', '‭', '‬', '‫', '‪',  # bidi overrides
            '​', '‌', '‍', '‎', '‏',  # zero-width
            '﻿',  # BOM
        )
        for ch in _DANGEROUS_UNICODE:
            filename = filename.replace(ch, '')
        try: filename = urllib.parse.unquote_plus(filename)
        except Exception: pass
        # Stripping path separators (/ and \) is what prevents directory traversal
        # - a Canvas filename like "../../evil" becomes "....evil" then gets
        # lstripped below. Do not remove these characters from the pattern.
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
        if replace_spaces: sanitized = sanitized.replace(' ', '_')
        sanitized = sanitized.lstrip(' _').rstrip('. _')
        
        base_upper = sanitized.split('.')[0].upper()
        if base_upper in ('CON', 'PRN', 'AUX', 'NUL') or \
           (len(base_upper) == 4 and base_upper[:-1] in ('COM', 'LPT') and base_upper[-1].isdigit()):
            sanitized = f"_{sanitized}"
            
        if len(sanitized) > max_length:
            name, ext = os.path.splitext(sanitized)
            if len(ext) > 10: sanitized = sanitized[:max_length]
            else: sanitized = name[:(max_length - len(ext))] + ext
        return sanitized if sanitized else "untitled"

    def clear_error_log(self, base_path):
        """Wipe download_errors.txt to start fresh for a new run."""
        self._logged_error_sigs = set()  # Reset dedup cache
        if not self.error_log_enabled:
            return
        if not base_path: return
        path = Path(base_path)
        log_file = path / "download_errors.txt"
        if path_exists(log_file):
            try:
                with _err_log_lock:
                    with open(make_long_path(log_file), "w", encoding="utf-8") as f:
                        f.write("")  # Truncate
            except Exception:
                pass

    def _log_error(self, base_path, error):
        """Log structured error to a single file in the root path. Deduplicates by signature."""
        # Build a signature to prevent the same error being logged twice
        if isinstance(error, DownloadError):
            error_sig = f"{error.course_name}|{error.item_name}|{error.message}"
        else:
            error_sig = str(error)
        if error_sig in self._logged_error_sigs:
            return  # Already logged this exact error in this run
        self._logged_error_sigs.add(error_sig)

        # Mirror EVERY structured error into the active debug log - with the
        # full traceback when the error wraps a real exception. Deduplicated
        # by the signature gate above, and independent of error_log_enabled
        # (debug mode opts into maximal forensics). Without this, unexpected
        # exceptions surfaced as bare one-liners in the UI and the debug log
        # had no record of WHERE they came from.
        try:
            from core.canvas_debug import log_debug_exc, get_active_debug_file
            _dbg_file = get_active_debug_file()
            if _dbg_file:
                if isinstance(error, DownloadError):
                    _summary = (
                        f"ERROR [{error.error_type}] {error.course_name} :: "
                        f"{error.item_name} :: {error.message}"
                    )
                    _raw = getattr(error, 'raw_error', None)
                else:
                    _summary, _raw = f"ERROR {error}", None
                if isinstance(_raw, BaseException):
                    log_debug_exc(_summary, _dbg_file, exc=_raw)
                else:
                    log_debug(_summary, _dbg_file)
        except Exception:
            pass  # diagnostics must never break the download

        # 'error' can be a DownloadError object or a string (legacy support)
        if not self.error_log_enabled:
            return
        if not base_path: return
        
        path = Path(base_path)
        Path(make_long_path(path)).mkdir(parents=True, exist_ok=True)
        log_file = path / "download_errors.txt"
        
        try:
            entry = ""
            if isinstance(error, DownloadError):
                entry = error.to_log_entry()
            else:
                entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error}"
                
            with _err_log_lock:
                with open(make_long_path(log_file), "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
        except Exception:
            # Last resort fallback if logging fails
            pass

    def _check_disk_space(self, path, min_free_gb=1, required_bytes=0):
        """Check disk space dynamically: max(min_free_gb, required_bytes * 1.2)."""
        try:
            stat = shutil.disk_usage(path)
            # Dynamic threshold: at least 1GB, or the payload size + 20% buffer
            min_required = max(min_free_gb * (1024**3), int(required_bytes * 1.2))
            return stat.free >= min_required
        except Exception:
            return True
