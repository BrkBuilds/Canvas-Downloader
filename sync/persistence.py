"""
sync.persistence — Atomic CRUD operations for sync pair configuration.

All mutations go through ``atomic_update_sync_pairs()`` which uses
``threading.Lock`` + ``.tmp`` file atomic replacement (``os.replace``)
to guard against cross-thread Streamlit tearing.

Extracted from ``sync_ui.py`` L91-158 (Phase 4).
"""

from __future__ import annotations

import streamlit as st
from ui_helpers import load_sync_pairs, atomic_update_sync_pairs


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
    def modifier(fresh_pairs):
        target_cid = new_pair.get('course_id')
        target_folder = new_pair.get('local_folder')
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
    def modifier(fresh_pairs):
        for new_pair in new_pairs_list:
            target_cid = new_pair.get('course_id')
            target_folder = new_pair.get('local_folder')
            exists = any(
                p.get('course_id') == target_cid and p.get('local_folder') == target_folder
                for p in fresh_pairs
            )
            if not exists:
                fresh_pairs.append(new_pair)
        return fresh_pairs
    st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)


def update_pair_by_signature(old_signature: dict, new_pair_data: dict) -> None:
    """Replace a specific pair identified by course_id + local_folder."""
    def modifier(fresh_pairs):
        for idx, p in enumerate(fresh_pairs):
            if (p.get('course_id') == old_signature.get('course_id') and
                    p.get('local_folder') == old_signature.get('local_folder')):
                fresh_pairs[idx] = new_pair_data
                break
        return fresh_pairs
    st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)


def update_last_synced_batch(updates_list: list) -> None:
    """Batch-update last_synced timestamps: [(course_id, folder, ts), ...]."""
    def modifier(fresh_pairs):
        for cid, folder, ts in updates_list:
            for p in fresh_pairs:
                if p.get('course_id') == cid and p.get('local_folder') == folder:
                    p['last_synced'] = ts
                    break
        return fresh_pairs
    st.session_state['sync_pairs'] = atomic_update_sync_pairs(modifier)


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
