"""
Preset Manager - Saved Download Settings & Presets for Step 2.

Persists user-defined presets to a JSON file and provides 5 built-in
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
    PANOPTO_OUTPUT_KEYS as _PANOPTO_OUTPUT_KEYS,
)

PRESETS_FILENAME = "saved_download_presets.json"

_presets_lock = threading.RLock()


class PresetManager:
    """CRUD operations for download-settings presets."""

    # ── The session-state keys that define a preset ─────────────────
    SECONDARY_CONTENT_KEYS = _SECONDARY_CONTENT_KEYS
    NOTEBOOK_SUB_KEYS = _NOTEBOOK_SUB_KEYS
    PANOPTO_OUTPUT_KEYS = _PANOPTO_OUTPUT_KEYS

    SETTINGS_KEYS = [
        'download_mode', 'file_filter', 'dl_isolate_secondary',
        *SECONDARY_CONTENT_KEYS,
        'dl_secondary_master',
        'notebooklm_master',
        *NOTEBOOK_SUB_KEYS,
        # Panopto (Section 4) output formats + layout. pan_layout is a string
        # ('match'|'separate'); the pan_out_* keys are booleans. Spread from the
        # registry rather than listed, so an output added to the card is part of
        # every preset by construction - a user preset that silently omitted one
        # would carry the previous preset's setting for it.
        *PANOPTO_OUTPUT_KEYS,
        'pan_layout',
    ]

    # ── 5 Immutable Built-in Presets ────────────────────────────────
    # Mirror the Quick Download presets exactly so both entry points
    # offer the same configurations.

    _BUILTIN_PRESETS = [
        {
            'preset_id': 'builtin_full_canvas',
            'preset_name': 'Complete Canvas Download',
            'description': (
                'Downloads everything as shown on Canvas - all files '
                'organized by module, with assignments, syllabus, '
                'discussions, quizzes, announcements, and submissions. '
                'Panopto video recordings included.'
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
                'pan_out_url': False,
                'pan_out_mp4': True,
                'pan_out_mp3': False,
                'pan_out_txt': False,
                'pan_out_srt': False,
                'pan_layout': 'match',
            },
            'include_path': False,
            'download_path': '',
        },
        {
            'preset_id': 'builtin_daily_study',
            'preset_name': 'Daily Study Pack (Optimized)',
            'description': (
                'All course files organized by module, with PowerPoints '
                'and Word docs converted to PDF for AI compatibility. '
                'Canvas Content is isolated in separate folders. '
                'Includes both Panopto video and audio.'
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
                'pan_out_url': False,
                'pan_out_mp4': True,
                'pan_out_mp3': True,
                'pan_out_txt': False,
                'pan_out_srt': False,
                'pan_layout': 'match',
            },
            'include_path': False,
            'download_path': '',
        },
        {
            'preset_id': 'builtin_notebooklm',
            'preset_name': '100% AI & NotebookLM Ready',
            'description': (
                'Everything in one flat folder with all file types '
                'converted to AI-friendly formats (PPTX, Word, Excel, '
                'HTML, code, links, video). Panopto audio saved '
                'separately. Drag-and-drop ready for NotebookLM.'
            ),
            'is_builtin': True,
            'settings': {
                'download_mode': 'flat',
                'file_filter': 'all',
                'dl_isolate_secondary': True,
                'dl_assignments': True,
                'dl_syllabus': True,
                'dl_announcements': True,
                'dl_discussions': True,
                'dl_quizzes': True,
                'dl_submissions': True,
                'dl_secondary_master': True,
                'notebooklm_master': True,
                'convert_zip': True,
                'convert_pptx': True,
                'convert_word': True,
                'convert_excel': True,
                'convert_html': True,
                'convert_code': True,
                'convert_urls': True,
                'convert_video': True,
                'pan_out_url': False,
                'pan_out_mp4': False,
                'pan_out_mp3': True,
                'pan_out_txt': False,
                'pan_out_srt': False,
                'pan_layout': 'separate',
            },
            'include_path': False,
            'download_path': '',
        },
        {
            'preset_id': 'builtin_slides_pdfs',
            'preset_name': 'Slides & PDFs Only',
            'description': (
                'Downloads only lecture slides and PDFs - no Canvas '
                'Content, no conversions, no Panopto. The fastest, '
                'most focused download for studying core materials.'
            ),
            'is_builtin': True,
            'settings': {
                'download_mode': 'modules',
                'file_filter': 'study',
                'dl_isolate_secondary': False,
                'dl_assignments': False,
                'dl_syllabus': False,
                'dl_announcements': False,
                'dl_discussions': False,
                'dl_quizzes': False,
                'dl_submissions': False,
                'dl_secondary_master': False,
                'notebooklm_master': False,
                'convert_zip': False,
                'convert_pptx': False,
                'convert_word': False,
                'convert_excel': False,
                'convert_html': False,
                'convert_code': False,
                'convert_urls': False,
                'convert_video': False,
                'pan_out_url': False,
                'pan_out_mp4': False,
                'pan_out_mp3': False,
                'pan_out_txt': False,
                'pan_out_srt': False,
                'pan_layout': 'match',
            },
            'include_path': False,
            'download_path': '',
        },
        {
            'preset_id': 'builtin_files_only',
            'preset_name': 'Files Only',
            'description': (
                'Only the files your teacher uploaded, organized by '
                'Canvas module. Skips all Canvas-generated content '
                '(assignments, announcements, discussions) and '
                'Panopto recordings.'
            ),
            'is_builtin': True,
            'settings': {
                'download_mode': 'modules',
                'file_filter': 'all',
                'dl_isolate_secondary': False,
                'dl_assignments': False,
                'dl_syllabus': False,
                'dl_announcements': False,
                'dl_discussions': False,
                'dl_quizzes': False,
                'dl_submissions': False,
                'dl_secondary_master': False,
                'notebooklm_master': False,
                'convert_zip': False,
                'convert_pptx': False,
                'convert_word': False,
                'convert_excel': False,
                'convert_html': False,
                'convert_code': False,
                'convert_urls': False,
                'convert_video': False,
                # Panopto: none. Must mirror ui/quick_download.py's
                # `quick_files_only` exactly - "Files Only" means just the
                # teacher's uploaded files, so this preset must never pull
                # multi-GB lecture videos (matching its "no distractions"
                # promise and "Slides & PDFs Only" above). Guarded by
                # tests/test_preset_parity.py.
                'pan_out_url': False,
                'pan_out_mp4': False,
                'pan_out_mp3': False,
                'pan_out_txt': False,
                'pan_out_srt': False,
                'pan_layout': 'match',
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
        """Load user-defined presets from disk. Never raises.

        For DISPLAY. A read-modify-write must use
        :meth:`_load_presets_for_update` instead - see its docstring.
        """
        return self._load_presets_for_update()[0]

    def _load_presets_for_update(self) -> tuple[list[dict], bool]:
        """``(presets, may_write)`` - the stored presets and the write verdict.

        Two defects lived in the single-return version, and they are the same two
        this repo has already fixed in ``core.library``, ``atomic_update_sync_pairs``
        and the shared settings file:

        **1. ``UnicodeDecodeError`` escaped entirely.** It is a *sibling* of
        ``json.JSONDecodeError``, not a subclass - both are ``ValueError`` - so
        neither the ``JSONDecodeError`` handler nor the ``IOError`` one caught it,
        and it propagated out of a function documented as returning a list. The
        caller is ``ui/presets.py``'s hub, inside an ``@st.dialog``, where a raise
        blanks the modal. Reproduced: one presets file re-saved by an editor in a
        Danish ANSI codepage (``Økonomi`` as cp1252) is enough, and preset names
        are typed by the user, so ``æøå`` is ordinary here.

        **2. A transient failure degraded to ``[]``, and the callers then WROTE.**
        ``save_preset`` and ``delete_preset`` both do load -> mutate -> save, so an
        antivirus lock or an offline share at the wrong moment replaced the user's
        entire preset library with the one preset they were adding. The old
        ``IOError`` branch even said "Do NOT recover or unlink" - it protected the
        FILE and then handed the caller an empty list to overwrite it with.

        Split by cause, so the answer matches the problem:

        * damaged content -> quarantine (the content survives on disk) and allow
          the write, so the user gets a working presets file back;
        * transient ``OSError`` -> ``may_write=False``; the caller must not write.
        """
        with _presets_lock:
            if not self.presets_path.exists():
                return [], True
            try:
                with open(self.presets_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except OSError as e:
                # Nothing is wrong with the FILE. Refuse the write rather than
                # replace a whole preset library with whatever this call adds.
                logger.error(f"Temporary file access error in load_presets: {e}")
                return [], False
            except Exception as e:
                # Damaged content: malformed JSON, or bytes that are not UTF-8.
                self._quarantine_presets(f"{type(e).__name__}: {e}")
                return [], True

            # A well-formed file with the wrong SHAPE is deliberately left in
            # place, not quarantined: it is not corruption, and the next save
            # overwrites the whole file anyway. That is a pre-existing decision
            # with its own test - see test_a_structurally_wrong_file_is_NOT_backed_up.
            if not isinstance(data, dict):
                logger.warning(f"Presets file has invalid root type: {type(data)}")
                return [], True
            presets = data.get('presets', [])
            if not isinstance(presets, list):
                return [], True
            return presets, True

    def _quarantine_presets(self, reason: str) -> None:
        """Move a damaged presets file aside so its content survives on disk.

        Keeps this module's own long-standing policy rather than adopting the
        shared helper's: the destination is ``.corrupt`` (not ``.corrupt.json``)
        and a stale backup is replaced, so the NEWEST corrupt copy is the one
        preserved. Both are pinned by tests in ``tests/test_preset_manager.py``
        and both are defensible here - after a first corruption the store is
        rebuilt from empty, so the newer copy holds the more recent presets. (The
        sync manifest keeps the FIRST copy instead, for the opposite and equally
        good reason: there, the earliest backup is the one closest to the last
        good sync.)

        What is NOT kept is the old "last resort: delete the corrupt file"
        branch. A corrupt presets file can still be salvaged by hand; a deleted
        one cannot, and saving works again regardless because
        ``_save_all_locked`` rewrites the whole file.
        """
        try:
            backup = self.presets_path.with_suffix('.corrupt')
            # Windows: Path.rename raises FileExistsError when the destination
            # exists, so the stale backup goes first.
            backup.unlink(missing_ok=True)
            self.presets_path.rename(backup)
            logger.warning(f"Presets file is corrupted ({reason}); backed up to {backup.name}")
        except Exception as e:
            logger.warning(
                f"Presets file is corrupted ({reason}) and could not be backed "
                f"up ({e}); leaving it in place - the next save overwrites it.")

    def get_builtin_presets(self) -> list[dict]:
        """Return the 5 immutable built-in presets (deep copies)."""
        import copy
        return copy.deepcopy(self._BUILTIN_PRESETS)

    # ── Write (Atomic) ──────────────────────────────────────────────

    def _save_all_locked(self, presets: list[dict]):
        """Atomically persist the full presets list to disk.

        Must be called while holding _presets_lock.
        Pattern: write to `.tmp`, fsync, then `os.replace`.
        """
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
        except Exception as e:
            logger.warning(f"Failed to save presets: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _save_all(self, presets: list[dict]):
        """Public alias: acquire lock then delegate to _save_all_locked."""
        with _presets_lock:
            self._save_all_locked(presets)

    def save_preset(
        self,
        name: str,
        description: str,
        settings: dict,
        include_path: bool,
        download_path: str,
    ) -> dict | None:
        """Create and persist a new user preset.

        Returns:
            The newly created preset dict, or ``None`` when the existing presets
            could not be read and saving would therefore have destroyed them.
        """
        with _presets_lock:
            presets, may_write = self._load_presets_for_update()
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
            if not may_write:
                # The existing presets could not be read. Appending to the empty
                # list we were handed would persist ONLY this preset and destroy
                # every other one the user has saved.
                #
                # Returns None rather than raising: the call site is inside an
                # @st.dialog with no handler, where an exception blanks the modal.
                # Same rule as write_config_atomically - a persistence failure
                # must not be able to abort the user's action, it must be
                # REPORTED. The caller says so instead of toasting success.
                logger.error("Not saving preset %r: the presets file could not "
                             "be read, so a write would discard the rest.", name)
                return None
            presets.append(new_preset)
            self._save_all_locked(presets)
        return new_preset

    def delete_preset(self, preset_id: str) -> bool:
        """Delete a user preset by ID.

        Built-in presets are immutable and cannot be deleted.

        Returns:
            True if found and deleted, False otherwise.
        """
        with _presets_lock:
            presets, may_write = self._load_presets_for_update()
            if not may_write:
                # An empty list here is "could not read", NOT "you have no
                # presets". Falling through would rewrite the file with [] and
                # delete every preset the user has - while reporting the ordinary
                # "not found" answer, so nothing on screen would say what
                # happened.
                logger.error("Not deleting preset %r: the presets file could "
                             "not be read.", preset_id)
                return False
            original_len = len(presets)
            presets = [p for p in presets if p.get('preset_id') != preset_id]
            if len(presets) == original_len:
                return False
            self._save_all_locked(presets)
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
            elif key == 'pan_layout':
                settings[key] = session_state.get(key, 'match')
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
                # Coerce unknown/legacy values (e.g. 'files' from an old
                # preset file) to 'modules' - only the two UI-reachable
                # modes are supported by the download engine's hybrid logic.
                _mode = settings.get(key, 'modules')
                session_state[key] = _mode if _mode in ('modules', 'flat') else 'modules'
            elif key == 'file_filter':
                session_state[key] = settings.get(key, 'all')
            elif key == 'pan_layout':
                _pl = settings.get(key, 'match')
                session_state[key] = _pl if _pl in ('match', 'separate') else 'match'
            else:
                session_state[key] = settings.get(key, False)

        # 2. Re-derive master toggles from sub-states.
        # Master is True when ANY sub-key is active (mirrors download_settings logic).
        sec_active = sum(
            1 for k in self.SECONDARY_CONTENT_KEYS
            if session_state.get(k, False)
        )
        session_state['dl_secondary_master'] = sec_active > 0

        nb_active = sum(
            1 for k in self.NOTEBOOK_SUB_KEYS
            if session_state.get(k, False)
        )
        session_state['notebooklm_master'] = nb_active > 0

        # 3. Optionally apply path (only if preset explicitly includes one)
        if preset.get('include_path') and preset.get('download_path'):
            session_state['download_path'] = preset['download_path']
