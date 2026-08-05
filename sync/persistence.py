"""
sync.persistence - Atomic CRUD operations for sync pair configuration.

All mutations go through ``atomic_update_sync_pairs()`` which uses
``threading.Lock`` + ``.tmp`` file atomic replacement (``os.replace``)
to guard against cross-thread Streamlit tearing.

Extracted from ``sync_ui.py`` L91-158 (Phase 4).
"""

from __future__ import annotations

import os
import streamlit as st
from pathlib import Path
from shared.helpers import load_sync_pairs, atomic_update_sync_pairs


# M-10: Roots that should never be used as a sync folder.
_BAD_ROOTS_WIN = {
    'c:\\windows', 'c:\\program files', 'c:\\program files (x86)', 'c:\\programdata',
}
_BAD_ROOTS_NIX = {'/etc', '/usr', '/bin', '/sbin', '/var', '/sys', '/proc'}


def _strip_label(pair: dict) -> dict:
    """Drop a course's user-chosen NAME before it enters the sync-pairs file.

    A label belongs to the ``(course_id, local_folder)`` link and is resolved at
    render from Saved Groups & Pairs (``core.pair_labels``) - deliberately never
    copied, because a copy is a thing that can disagree with its source.

    The hub hands its OWN pair dicts straight to the sync list ("Add to Sync
    List" for a group, and rescue mode), and a group member's dict carries
    ``label``. Without this the name would be written into
    ``canvas_sync_pairs.json`` as a second, silently-stale copy - inert today
    because nothing reads it, and a trap for the first person who does. Stripped
    HERE rather than at the three call sites so a future one cannot forget.

    ``today_store._norm_pair`` performs the same duty for the daily list.
    """
    if not isinstance(pair, dict) or 'label' not in pair:
        return pair
    return {k: v for k, v in pair.items() if k != 'label'}


def _with_saved_id(pair: dict) -> dict:
    """Tag a pair with the id of the saved library pair it references, so the
    working sync list follows a later hub rename / re-link by that STABLE id
    (folder moves included). A raw pair with no saved match is left untouched.

    Persisting the id is what makes a re-link followable: until an entry has been
    written through here (or through ``_resolve_active_pairs`` on any
    ``atomic_update_sync_pairs`` write), it is bound to its library pair only by
    LINK, so a hub re-link that moves the folder before any write breaks that
    link and the entry degrades to a raw copy (keeps its last-known folder/name)
    rather than following. It self-heals on the next add / remove / sync, all of
    which persist the id. In practice writes are frequent (every sync stamps
    last_synced), so the window is small."""
    if not isinstance(pair, dict) or pair.get('saved_id'):
        return pair
    try:
        import core.library as library
        p = library.pair_for(pair.get('course_id'), pair.get('local_folder'))
        if p is not None:
            return {**pair, 'saved_id': p['id']}
    except Exception:
        pass
    return pair


def _validate_pair_folder(folder: str) -> bool:
    """Return False if folder is an obviously dangerous system root."""
    try:
        p_lower = str(Path(folder).resolve()).lower()
        sep = os.sep
        for bad in _BAD_ROOTS_WIN | _BAD_ROOTS_NIX:
            if p_lower == bad or p_lower.startswith(bad + sep) or p_lower.startswith(bad + '/'):
                return False
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════
# Read
# ═══════════════════════════════════════════════

def load_persistent_pairs() -> None:
    """Load persistent pairs from disk into session state (once)."""
    if 'sync_pairs_loaded' not in st.session_state:
        saved = load_sync_pairs()
        if saved and not st.session_state.get('sync_pairs'):
            st.session_state['sync_pairs'] = saved
        st.session_state['sync_pairs_loaded'] = True


# ═══════════════════════════════════════════════
# Create / Update
# ═══════════════════════════════════════════════

def add_pair(new_pair: dict) -> None:
    """Add a single sync pair (deduplicates by course_id + local_folder)."""
    new_pair = _with_saved_id(_strip_label(new_pair))
    target_folder = new_pair.get('local_folder', '')
    if not _validate_pair_folder(target_folder):
        st.toast(f"Folder rejected - system folders cannot be used as sync folders: {target_folder}", icon="⚠️")
        return
    def modifier(fresh_pairs):
        target_cid = new_pair.get('course_id')
        exists = any(
            p.get('course_id') == target_cid and p.get('local_folder') == target_folder
            for p in fresh_pairs
        )
        if not exists:
            fresh_pairs.append(new_pair)
        return fresh_pairs
    st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)


def add_pairs_batch(new_pairs_list: list[dict]) -> None:
    """Add multiple sync pairs in a single atomic operation."""
    rejected = []
    new_pairs_list = [_with_saved_id(_strip_label(p)) for p in new_pairs_list]
    def modifier(fresh_pairs):
        for new_pair in new_pairs_list:
            target_cid = new_pair.get('course_id')
            target_folder = new_pair.get('local_folder', '')
            if not _validate_pair_folder(target_folder):
                rejected.append(target_folder)
                continue
            exists = any(
                p.get('course_id') == target_cid and p.get('local_folder') == target_folder
                for p in fresh_pairs
            )
            if not exists:
                fresh_pairs.append(new_pair)
        return fresh_pairs
    st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)
    if rejected:
        st.toast(f"{len(rejected)} folder(s) rejected - system folders cannot be used as sync folders.", icon="⚠️")


def update_pair_by_signature(old_signature: dict, new_pair_data: dict) -> None:
    """Replace a specific pair identified by course_id + local_folder."""
    new_pair_data = _strip_label(new_pair_data)
    def modifier(fresh_pairs):
        for idx, p in enumerate(fresh_pairs):
            if (p.get('course_id') == old_signature.get('course_id') and
                    p.get('local_folder') == old_signature.get('local_folder')):
                fresh_pairs[idx] = new_pair_data
                break
        return fresh_pairs
    st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)


def update_last_synced_batch(updates_list: list) -> None:
    """Batch-update last_synced timestamps: [(course_id, folder, ts), ...].

    The ONLY mutator here that is called by the sync ENGINE rather than by the
    Sync page's own CRUD - and that is exactly why it must NOT assign the
    persisted list over ``st.session_state['sync_pairs']`` the way its four
    siblings do. For them the session list and the file are the same set by
    construction, so the assignment is a no-op. The engine also runs for the
    Today dashboard, whose ``sync_pairs`` is a CURATED SUBSET published by
    ``core.auto_sync.start_today_sync`` from ``today_dashboard.json`` and never
    written to ``canvas_sync_pairs.json`` at all.

    So the assignment used to replace the running Today sync's pair list with
    whatever the Sync page happened to have saved. For a user who only ever used
    Saved Groups & Pairs that file is ``[]``, and the run's own pair list was
    wiped the instant it finished - stranding ``render_sync_step4`` on its
    "No course folders found" notice with no way to reach the completion
    handler, so the Today notice was never built and ``cleanup_sync_state()``
    never ran (measured 2026-07-31 in the frozen build: a 203-file Quick Sync
    downloaded everything successfully and then hung on that screen).

    Stamping the session's own list in place keeps both flows correct: the Sync
    page sees the same pairs it already had, now timestamped, and Today keeps
    its subset.
    """
    def modifier(fresh_pairs):
        for cid, folder, ts in updates_list:
            for p in fresh_pairs:
                if p.get('course_id') == cid and p.get('local_folder') == folder:
                    p['last_synced'] = ts
                    break
        return fresh_pairs

    atomic_update_sync_pairs(modifier)

    # Same transformation, applied to the session's working list - deliberately
    # the SAME callable, so the persisted and in-memory stamps can never drift.
    session_pairs = st.session_state.get('sync_pairs')
    if isinstance(session_pairs, list):
        modifier(session_pairs)


# ═══════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════

def remove_pairs_by_signature(signatures_to_remove: list[dict]) -> None:
    """Remove pairs matching any of the given course_id + local_folder signatures."""
    def modifier(fresh_pairs):
        def should_keep(p):
            for sig in signatures_to_remove:
                if (p.get('course_id') == sig.get('course_id') and
                        p.get('local_folder') == sig.get('local_folder')):
                    return False
            return True
        return [p for p in fresh_pairs if should_keep(p)]
    st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)
