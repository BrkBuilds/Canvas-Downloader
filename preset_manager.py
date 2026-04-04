"""
Preset Manager — Saved Download Settings & Presets for Step 2.

Persists user-defined presets to a JSON file and provides 3 built-in
immutable presets.  Uses the same atomic serialization pattern as
SavedGroupsManager (`.tmp` + `os.replace` + `threading.Lock`).
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from core.state_registry import (
    SECONDARY_CONTENT_KEYS as _SECONDARY_CONTENT_KEYS,
    NOTEBOOK_SUB_KEYS as _NOTEBOOK_SUB_KEYS,
)

PRESETS_FILENAME = "saved_download_presets.json"

_presets_lock = threading.Lock()


class PresetManager:
    """CRUD operations for download-settings presets."""

    # ── The 19 session-state keys that define a preset ──────────────
    SECONDARY_CONTENT_KEYS = _SECONDARY_CONTENT_KEYS
    NOTEBOOK_SUB_KEYS = _NOTEBOOK_SUB_KEYS

    SETTINGS_KEYS = [
        'download_mode', 'file_filter', 'dl_isolate_secondary',
        *SECONDARY_CONTENT_KEYS,
        'dl_secondary_master',
        'notebooklm_master',
        *NOTEBOOK_SUB_KEYS,
    ]

    # ── 3 Immutable Built-in Presets ────────────────────────────────

    _BUILTIN_PRESETS = [
        {
            'preset_id': 'builtin_full_canvas',
            'preset_name': '1:1 Full Canvas Course Download',
            'description': (
                'Downloads the course files and Canvas content exactly '
                'like they are displayed on Canvas.'
            ),
            'is_builtin': True,
            'settings': {
                'download_mode': 'modules',
                'file_filter': 'all',
                'dl_isolate_secondary': False,
                'dl_assignments': True,
                'dl_syllabus': True,
                'dl_announcements': True,
                'dl_discussions': True,
                'dl_quizzes': True,
                'dl_rubrics': True,
                'dl_submissions': True,
                'dl_secondary_master': True,
                'notebooklm_master': False,
                'convert_zip': True,
                'convert_pptx': False,
                'convert_word': False,
                'convert_excel': False,
                'convert_html': False,
                'convert_code': False,
                'convert_urls': False,
                'convert_video': False,
            },
            'include_path': False,
            'download_path': '',
        },
        {
            'preset_id': 'builtin_ai_power_user',
            'preset_name': 'AI Power-User Student',
            'description': (
                'Downloads course files as organized by the teacher, '
                'but optimizes core files for AI. Canvas Content is '
                'isolated in separate folders to keep you updated.'
            ),
            'is_builtin': True,
            'settings': {
                'download_mode': 'modules',
                'file_filter': 'all',
                'dl_isolate_secondary': True,
                'dl_assignments': True,
                'dl_syllabus': True,
                'dl_announcements': True,
                'dl_discussions': True,
                'dl_quizzes': True,
                'dl_rubrics': True,
                'dl_submissions': True,
                'dl_secondary_master': True,
                'notebooklm_master': False,
                'convert_zip': True,
                'convert_pptx': True,
                'convert_word': True,
                'convert_excel': False,
                'convert_html': False,
                'convert_code': False,
                'convert_urls': False,
                'convert_video': False,
            },
            'include_path': False,
            'download_path': '',
        },
        {
            'preset_id': 'builtin_notebooklm',
            'preset_name': 'NotebookLM Optimized (Drag-and-Drop)',
            'description': (
                "Downloads only the core files from the Canvas 'files' "
                'tab and converts them to AI-friendly formats in a '
                'single folder. Ready to drag and drop into NotebookLM.'
            ),
            'is_builtin': True,
            'settings': {
                'download_mode': 'flat',
                'file_filter': 'all',
                'dl_isolate_secondary': False,
                'dl_assignments': False,
                'dl_syllabus': False,
                'dl_announcements': False,
                'dl_discussions': False,
                'dl_quizzes': False,
                'dl_rubrics': False,
                'dl_submissions': False,
                'dl_secondary_master': False,
                'notebooklm_master': True,
                'convert_zip': True,
                'convert_pptx': True,
                'convert_word': True,
                'convert_excel': True,
                'convert_html': True,
                'convert_code': True,
                'convert_urls': True,
                'convert_video': True,
            },
            'include_path': False,
            'download_path': '',
        },
    ]

    # ── Constructor ─────────────────────────────────────────────────

    def __init__(self, config_dir: str):
        self.presets_path = Path(config_dir) / PRESETS_FILENAME

    # ── Read ────────────────────────────────────────────────────────

    def load_presets(self) -> list[dict]:
        """Load user-defined presets from disk.

        Returns:
            List of preset dicts (never includes built-ins).
        """
        if not self.presets_path.exists():
            return []
        try:
            with open(self.presets_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            presets = data.get('presets', [])
            if not isinstance(presets, list):
                return []
            return presets
        except (json.JSONDecodeError, IOError):
            return []

    def get_builtin_presets(self) -> list[dict]:
        """Return the 3 immutable built-in presets (deep copies)."""
        import copy
        return copy.deepcopy(self._BUILTIN_PRESETS)

    # ── Write (Atomic) ──────────────────────────────────────────────

    def _save_all(self, presets: list[dict]):
        """Atomically persist the full presets list to disk.

        Pattern: write to `.tmp`, fsync, then `os.replace`.
        """
        with _presets_lock:
            tmp_path = self.presets_path.with_suffix('.tmp')
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        {'presets': presets}, f,
                        indent=2, ensure_ascii=False,
                    )
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(str(tmp_path), str(self.presets_path))
            except IOError as e:
                logger.warning(f"Failed to save presets: {e}")
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass

    def save_preset(
        self,
        name: str,
        description: str,
        settings: dict,
        include_path: bool,
        download_path: str,
    ) -> dict:
        """Create and persist a new user preset.

        Returns:
            The newly created preset dict.
        """
        presets = self.load_presets()
        new_preset = {
            'preset_id': f"preset_{uuid.uuid4().hex[:12]}",
            'preset_name': name.strip(),
            'description': description.strip() if description else '',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'is_builtin': False,
            'settings': settings,
            'include_path': include_path,
            'download_path': download_path if include_path else '',
        }
        presets.append(new_preset)
        self._save_all(presets)
        return new_preset

    def delete_preset(self, preset_id: str) -> bool:
        """Delete a user preset by ID.

        Built-in presets are immutable and cannot be deleted.

        Returns:
            True if found and deleted, False otherwise.
        """
        presets = self.load_presets()
        original_len = len(presets)
        presets = [p for p in presets if p.get('preset_id') != preset_id]
        if len(presets) == original_len:
            return False
        self._save_all(presets)
        return True

    # ── State Capture & Apply ───────────────────────────────────────

    def capture_current_settings(self, session_state) -> dict:
        """Snapshot the current session state into a settings dict.

        Uses `.get()` with safe defaults so missing keys never crash.
        """
        settings = {}
        for key in self.SETTINGS_KEYS:
            if key == 'download_mode':
                settings[key] = session_state.get(key, 'modules')
            elif key == 'file_filter':
                settings[key] = session_state.get(key, 'all')
            else:
                settings[key] = session_state.get(key, False)
        return settings

    def apply_preset(self, session_state, preset: dict):
        """Write all preset settings into session state.

        Re-derives the two master toggles from their sub-states to
        guarantee visual consistency regardless of what was stored.
        Only overwrites `download_path` when the preset explicitly
        carries a valid, non-empty path.
        """
        settings = preset.get('settings', {})

        # 1. Apply each setting key with safe defaults
        for key in self.SETTINGS_KEYS:
            if key == 'download_mode':
                session_state[key] = settings.get(key, 'modules')
            elif key == 'file_filter':
                session_state[key] = settings.get(key, 'all')
            else:
                session_state[key] = settings.get(key, False)

        # 2. Re-derive master toggles from sub-states
        sec_active = sum(
            1 for k in self.SECONDARY_CONTENT_KEYS
            if session_state.get(k, False)
        )
        session_state['dl_secondary_master'] = (
            sec_active == len(self.SECONDARY_CONTENT_KEYS)
        )

        nb_active = sum(
            1 for k in self.NOTEBOOK_SUB_KEYS
            if session_state.get(k, False)
        )
        session_state['notebooklm_master'] = (
            nb_active == len(self.NOTEBOOK_SUB_KEYS)
        )

        # 3. Optionally apply path (only if preset explicitly includes one)
        if preset.get('include_path') and preset.get('download_path'):
            session_state['download_path'] = preset['download_path']
