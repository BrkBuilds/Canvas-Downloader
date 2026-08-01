"""core.pair_labels - the user's own name for a course/folder pair.

WHAT THIS IS
------------
Sync mode has always had exactly one name for a course: the one Canvas gave it.
The user CAN write their own name - "Save as Pair" asks for one, and every
saved group has one - but that name was trapped in the Saved Groups & Pairs
hub: "Add to Sync List" copies ``{local_folder, course_id, course_name}`` onto
the sync list and drops the name on the floor. So the one place the user had
expressed what they call a course was the one place it was never shown.

This module is the resolver that fixes that, and it has exactly one rule:

    A LABEL BELONGS TO A LINK, NOT TO A RECORD.

The link is ``(course_id, local_folder)`` - the tuple every dedupe, update,
remove and reconcile in this app already keys on. Anything that renders a pair
asks this module for that link's name; if there is none it falls back to
``friendly_course_name()`` and the screen looks exactly as it did before.

WHERE THE LABEL IS STORED (and why there is no new file)
--------------------------------------------------------
``saved_sync_groups.json``, which the user already curates, in two places:

* **A standalone saved pair** - its own name, i.e. the record's ``group_name``.
  That field name is a wart: ``SavedGroupsManager`` stores a saved PAIR as a
  group record holding one pair with ``is_single_pair: True``, so the pair's
  name lands in a field called ``group_name``. Nothing outside the manager
  should have to know that - read it through :func:`saved_record_label`.
* **A course inside a group** - an optional ``label`` on that pair entry.
  A group's name names the SET; it can never name one of its courses.

Consequences that are deliberate:

* Rename in the hub and every sync surface shows the new name on the next
  render. There is no copy of the label anywhere, so there is nothing to
  reconcile and nothing that can go stale - unlike the daily list's pair
  copies, which needed ``reconcile_daily_list_with_hub`` for exactly that.
* Delete the saved pair and the link reverts to its Canvas name everywhere.
* The daily list and the sync list keep storing plain pairs. Today's
  ``_norm_pair`` strips unknown keys and MUST keep doing so - a label carried
  in a copy is a label that can drift.

PRECEDENCE
----------
The same link can be a standalone saved pair AND a member of several groups
(the app deliberately does not stop that), so "the label" has to be decided,
not discovered:

    1. the standalone saved pair, first in file order;
    2. otherwise a group member's ``label``, first in file order.

A standalone pair wins because it is the record whose ENTIRE purpose is to name
that one link. Nothing enforces uniqueness upstream (the hub's Edit Pair can
retarget a pair onto another's link), so this order is what makes the answer
stable rather than dependent on how the file happens to be ordered.

AUTO-NAMED PAIRS CONTRIBUTE NOTHING
-----------------------------------
The Save as Pair dialog pre-fills the course name as a placeholder so saving is
one click. Accepting that suggestion means "I didn't choose a name", so the
record is flagged ``auto_named`` and this module ignores it - the surfaces keep
showing the LIVE Canvas name and a course renamed on Canvas follows along.
Typing anything clears the flag and the user's name wins from then on.

CACHING
-------
Memoised on the groups file's ``(mtime_ns, size)``. That is correct by
construction: every write goes through ``_save_all``'s ``os.replace``, which
moves the mtime, so a stale index cannot survive a write. The alternative -
an explicit invalidate call at each of the hub's seven mutation sites - is one
forgotten call away from a name that does not update, and this file is small
enough that a re-read costs nothing.

Streamlit-free on purpose: the sync engine formats course names for its
progress UI, so this must not depend on a ScriptRunContext.
"""

from __future__ import annotations

import os
import threading

from shared.helpers import friendly_course_name, norm_folder_key

# A label is a TITLE. It becomes the heading on the sync-list card, the review
# and confirmation screens, the progress heading, the completion card, Today's
# chips and the sync-history run header - so an uncapped one does not degrade
# gracefully anywhere. Enforced at every input rather than at render, so what
# the user typed is always exactly what they see.
PAIR_LABEL_MAX_CHARS = 60

__all__ = [
    "PAIR_LABEL_MAX_CHARS",
    "pair_key",
    "build_label_index",
    "label_index",
    "label_for",
    "label_for_pair",
    "pair_display",
    "pair_display_name",
    "saved_record_label",
    "canvas_name_label_index",
]

_memo_lock = threading.Lock()
# (stat_signature, index) - see the CACHING note above.
_memo: tuple | None = None


# ── identity ─────────────────────────────────────────────────────────────────

def pair_key(course_id, local_folder) -> tuple:
    """The label key for a course/folder link.

    ``course_id`` is coerced to ``int`` when it looks like one: the hub stores
    whatever the course selector handed it, history has been through JSON, and
    ``42`` and ``"42"`` are the same course. Folder goes through the app's one
    normaliser so ``C:/x`` and ``C:\\X\\`` are the same folder.
    """
    try:
        cid = int(course_id)
    except (TypeError, ValueError):
        cid = course_id
    return (cid, norm_folder_key(local_folder))


def saved_record_label(record: dict) -> str:
    """The user-chosen name on a hub record, or ``''``.

    Reads the misnamed ``group_name`` field so no caller has to say "group"
    when it means a saved pair, and honours the ``auto_named`` flag: a pair
    saved by accepting the pre-filled suggestion has a stored name but no
    CHOSEN one, so it must not override the live Canvas name.
    """
    if not isinstance(record, dict) or record.get("auto_named"):
        return ""
    return (record.get("group_name") or "").strip()


# ── index ────────────────────────────────────────────────────────────────────

def build_label_index(groups) -> dict:
    """``{pair_key: label}`` from raw hub records. Pure - no I/O, no Streamlit.

    Two passes, not one, because the passes ARE the precedence rule: every
    standalone saved pair is claimed before any group member is considered.
    ``setdefault`` then makes "first in file order" the tie-break within each
    pass.
    """
    idx: dict = {}
    if not groups:
        return idx

    # Pass 1 - standalone saved pairs.
    for record in groups:
        if not isinstance(record, dict) or not record.get("is_single_pair"):
            continue
        name = saved_record_label(record)
        if not name:
            continue
        for p in record.get("pairs") or []:
            if isinstance(p, dict):
                idx.setdefault(pair_key(p.get("course_id"), p.get("local_folder")), name)

    # Pass 2 - per-course labels inside multi-course groups.
    for record in groups:
        if not isinstance(record, dict) or record.get("is_single_pair"):
            continue
        for p in record.get("pairs") or []:
            if not isinstance(p, dict):
                continue
            name = (p.get("label") or "").strip()
            if name:
                idx.setdefault(pair_key(p.get("course_id"), p.get("local_folder")), name)

    return idx


def _groups_stat(path) -> tuple:
    """Cheap change signature for the groups file. ``()`` when unreadable."""
    try:
        st_ = os.stat(path)
        return (st_.st_mtime_ns, st_.st_size)
    except OSError:
        return ()


def label_index(config_dir: str | None = None) -> dict:
    """The live ``{pair_key: label}`` map, memoised on the groups file's mtime.

    Total: any failure to read the hub degrades to "no labels", i.e. every
    surface shows the Canvas name it showed before this feature existed. A
    naming feature must never be able to break a sync screen.
    """
    global _memo
    try:
        from core.sync_manager import SavedGroupsManager
        if config_dir is None:
            from shared.helpers import get_config_dir
            config_dir = get_config_dir()
        mgr = SavedGroupsManager(config_dir)
        sig = (str(mgr.groups_path),) + _groups_stat(mgr.groups_path)

        with _memo_lock:
            if _memo is not None and _memo[0] == sig and sig[1:]:
                return _memo[1]

        idx = build_label_index(mgr.load_groups())
        with _memo_lock:
            _memo = (sig, idx)
        return idx
    except Exception:
        return {}


def canvas_name_label_index(config_dir: str | None = None) -> dict:
    """``{casefolded canvas name: label}`` - the fallback for records with no link.

    Sync history entries carry ``synced_groups`` (which do have course_id +
    local_folder) only when the run actually moved files; a "No changes" run
    leaves nothing but a list of course NAME strings. Without this those cards
    would be the one place in the app still showing the Canvas name, which
    reads as a bug rather than as a limitation.

    Both the stored form and its ``friendly_course_name`` form are keyed, since
    a pair's ``course_name`` may itself already be the disambiguated raw name
    (see ``sync_ui``'s collision handling) while history may hold either.
    """
    out: dict = {}
    try:
        from core.sync_manager import SavedGroupsManager
        if config_dir is None:
            from shared.helpers import get_config_dir
            config_dir = get_config_dir()
        idx = label_index(config_dir)
        if not idx:
            return out
        for record in SavedGroupsManager(config_dir).load_groups():
            if not isinstance(record, dict):
                continue
            for p in record.get("pairs") or []:
                if not isinstance(p, dict):
                    continue
                label = idx.get(pair_key(p.get("course_id"), p.get("local_folder")))
                if not label:
                    continue
                raw = (p.get("course_name") or "").strip()
                for variant in (raw, friendly_course_name(raw) or ""):
                    key = variant.strip().casefold()
                    if key:
                        out.setdefault(key, label)
    except Exception:
        return {}
    return out


# ── resolution ───────────────────────────────────────────────────────────────

def label_for(course_id, local_folder) -> str:
    """The user's name for this link, or ``''`` if they never gave one."""
    if not local_folder:
        return ""
    return label_index().get(pair_key(course_id, local_folder), "")


def label_for_pair(pair: dict) -> str:
    """:func:`label_for` for a pair dict from any of the app's pair lists."""
    if not isinstance(pair, dict):
        return ""
    return label_for(pair.get("course_id"), pair.get("local_folder"))


def pair_display(pair: dict, *, fallback: str = "Course") -> tuple:
    """``(label, canvas_name)`` for one pair - the ONE call every surface makes.

    ``label`` is ``''`` when the user never named this link, which is the
    signal to render exactly what was rendered before this feature existed.
    ``canvas_name`` is always populated, because the Canvas name is the pair's
    identity and no screen should be able to lose it.
    """
    if not isinstance(pair, dict):
        return ("", fallback)
    canvas = friendly_course_name(pair.get("course_name") or "") or fallback
    return (label_for_pair(pair), canvas)


def pair_display_name(pair: dict, *, fallback: str = "Course") -> str:
    """The single string to show where only one name fits - progress headings,
    toasts, notifications, completion cards.

    Named ``pair_display_name`` rather than ``display_name`` because almost
    every call site already has a local called ``display_name``; a bare import
    would shadow it silently at whichever site forgot.
    """
    label, canvas = pair_display(pair, fallback=fallback)
    return label or canvas
