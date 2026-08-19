"""Panopto settings persistence.

All Panopto configuration lives under a single ``"panopto"`` key inside the
app's main settings file (``canvas_downloader_settings.json`` in
``get_config_dir()``).  We use an atomic read-modify-write so other top-level
settings written by ui/auth.py's settings dialog are never clobbered, and vice
versa.

The settings dict shape (with defaults) is defined by ``PANOPTO_DEFAULTS``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_KEY = "panopto"

# Single source of truth for the Panopto config shape + defaults.
PANOPTO_DEFAULTS: dict = {
    # Master toggle: include Panopto recordings in download / sync runs.
    "enabled": False,
    # Output formats the user wants written per recording.
    # Default OFF, unlike the three below: this key did not exist before the
    # Shortcut output shipped, so every stored contract and every legacy folder
    # answers False for it. Defaulting it True would start writing a new file
    # beside every recording in every folder the app has ever synced, on the
    # first run after an update, without anyone asking for it.
    "output_url": False,       # link to the recording on Panopto
    "output_mp3": True,        # audio
    "output_txt": True,        # plain-text transcript
    "output_srt": True,        # timestamped subtitles
    "output_mp4": False,       # full video (combined MP4, stream-copied)
    # Transcription.
    # faster-whisper model id (see panopto.models). This static value is only a
    # schema placeholder / last-resort fallback: the effective default for a
    # machine with nothing persisted yet comes from
    # ``panopto.models.recommend_model()``, which reads the actual GPU VRAM or CPU
    # core count. A fixed default is wrong on most hardware - 'small' in
    # particular transcribes non-English lecture audio poorly.
    "model": "small",
    "language": "auto",        # 'auto' | ISO code ('da', 'en', ...)
    "device": "cpu",           # 'cpu' | 'cuda'
    # Output organization. Both layouts keep recordings INSIDE the course folder.
    #   'match'    -> save alongside course files (module subfolder in modules
    #                 mode, course root in flat mode).
    #   'separate' -> a "Panopto Recordings" subfolder inside the course folder,
    #                 with one subfolder per recording.
    "layout": "match",
}


def _config_path() -> Path:
    """Resolve the shared settings JSON path (lazy import of get_config_dir)."""
    from shared.helpers import get_config_dir
    return Path(get_config_dir()) / "canvas_downloader_settings.json"


def _read_full_config() -> dict:
    """The whole settings file, or ``{}``. READ-ONLY callers only.

    Degrading an unreadable file to ``{}`` is the correct answer for a caller
    that only wants to READ one key - it falls back to that key's default. It is
    the wrong answer for a read-modify-WRITE, which would then persist ``{}``
    plus its own key and destroy every other module's settings. Those callers use
    :func:`_read_full_config_for_update`.
    """
    data, _ = _read_full_config_for_update()
    return data


def _read_full_config_for_update() -> tuple[dict, bool]:
    """``(config, may_write)`` for a read-modify-write of the settings file.

    Thin wrapper over the ONE shared implementation so this module cannot drift
    from ``ui.auth`` and ``shared.legal``, which co-own the same file. See
    :func:`shared.helpers.read_json_for_update` for why the verdict is split by
    cause rather than collapsed to a dict.
    """
    from shared.helpers import read_json_for_update
    return read_json_for_update(_config_path())


def _atomic_write_config(full: dict, what: str) -> bool:
    """Write the WHOLE settings dict back atomically. Returns True on success.

    The one implementation of the tmp + fsync + ``os.replace`` dance for this
    module's three writers. It deliberately takes the already-merged dict and
    performs NO read: the read is the half that has to be split by cause (see
    :func:`_read_full_config_for_update`), and a writer that got its dict from
    anywhere else is exactly the bug ``tests/test_settings_coownership.py``
    exists to catch. Keeping the two halves separate is what lets that test go
    on asserting, per writer, that the safe reader was used.
    """
    path = _config_path()
    tmp = str(path) + ".tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(full, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warning(f"Could not save {what}: {e}")
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False


def load_settings() -> dict:
    """Return the persisted Panopto settings merged over defaults.

    Unknown/legacy keys in the stored dict are dropped; missing keys fall back
    to ``PANOPTO_DEFAULTS`` so the shape is always complete and predictable.
    """
    stored = _read_full_config().get(SETTINGS_KEY, {})
    if not isinstance(stored, dict):
        stored = {}
    merged = dict(PANOPTO_DEFAULTS)
    for k in PANOPTO_DEFAULTS:
        if k in stored:
            merged[k] = stored[k]
    return merged


def save_settings(settings: dict) -> bool:
    """Atomically persist the Panopto settings under the ``"panopto"`` key.

    Reads the whole config first so all other top-level keys are preserved,
    then writes via a temp file + os.replace. Returns True on success.
    """
    # Sanitize to the known shape so we never store stray keys.
    clean = dict(PANOPTO_DEFAULTS)
    for k in PANOPTO_DEFAULTS:
        if k in settings:
            clean[k] = settings[k]

    full, may_write = _read_full_config_for_update()
    if not may_write:
        # A transient read failure (offline share, AV lock). Writing now would
        # replace the accepted acceptable-use notice, the global on/off
        # preference and every download default with this one block.
        logger.warning("Not saving Panopto settings: the settings file could "
                       "not be read, so a write would discard the rest of it.")
        return False
    full[SETTINGS_KEY] = clean

    return _atomic_write_config(full, "the Panopto settings")


# ── Global on/off preference ────────────────────────────────────────────────
# A TOP-LEVEL key, deliberately NOT a member of PANOPTO_DEFAULTS: that dict is
# the schema for a per-run CONTRACT (save_settings sanitises to exactly its keys,
# compose_settings starts from a copy of it), so anything added there is copied
# into every run config and persisted into every synced folder's manifest. This
# is a standing preference about the user, not a property of a download - the
# same reasoning that keeps the acceptable-use acknowledgement top-level in
# shared/legal.py.
GLOBAL_ENABLED_KEY = "panopto_globally_enabled"


def is_globally_enabled() -> bool:
    """False only when the user has explicitly switched Panopto off.

    Defaults to True: off-by-default would silently strip a headline feature
    from every existing install and quietly neuter the three Quick Download
    presets that include recordings.
    """
    return bool(_read_full_config().get(GLOBAL_ENABLED_KEY, True))


def set_globally_enabled(enabled: bool) -> bool:
    """Persist the global Panopto preference. Returns True on success.

    Atomic read-modify-write so the ``"panopto"`` block and every other
    top-level key written by the Settings dialog survive untouched.
    """
    full, may_write = _read_full_config_for_update()
    if not may_write:
        logger.warning("Not saving the global Panopto preference: the settings "
                       "file could not be read, so a write would discard it.")
        return False
    full[GLOBAL_ENABLED_KEY] = bool(enabled)

    return _atomic_write_config(full, "the global Panopto preference")


# ── The "transcription isn't set up" notice: dismissal ──────────────────────
# TOP-LEVEL for the same reason as GLOBAL_ENABLED_KEY above: this is a standing
# preference about the USER ("I have read this, stop leading with it"), not a
# property of a download, so it must never reach PANOPTO_DEFAULTS and be copied
# into every run config and every synced folder's manifest.
#
# It exists because the notice reports a STANDING configuration mismatch rather
# than an event: a folder whose stored contract asks for Transcript/Subtitles
# with no model installed re-states that on every single render of the sync
# page, for ever. The three ways out are all heavy (install a model, switch
# Panopto off globally, or re-download the course with the outputs unticked) -
# a folder's panopto_contract is written by the download flow and no UI edits
# it - so without this the user has no proportionate answer at all.
#
# Dismissing NEVER hides the fact, it only stops it leading: the notice
# collapses to a one-line re-spawn link that is always present. That is the
# same shape as the Full Disk Access nudge (shared/components.render_fda_nudge)
# and for the same reason - this is operational state, not help text, so it is
# not allowed to disappear.
TX_NOTICE_DISMISSED_KEY = "transcription_setup_notice_dismissed"


def is_tx_setup_notice_dismissed() -> bool:
    """True once the user has collapsed the transcription-setup notice.

    Defaults to False: the first time a folder is configured for transcripts
    without a model, the full card is the right thing to show.
    """
    return bool(_read_full_config().get(TX_NOTICE_DISMISSED_KEY, False))


def set_tx_setup_notice_dismissed(dismissed: bool = True) -> bool:
    """Persist the transcription-notice dismissal. Returns True on success.

    Atomic read-modify-write through the for-update reader, like every other
    writer of this co-owned file - a degrading read here would replace the
    accepted acceptable-use notice, the global switch and every download
    default with this one flag.
    """
    full, may_write = _read_full_config_for_update()
    if not may_write:
        logger.warning("Not saving the transcription-notice dismissal: the "
                       "settings file could not be read, so a write would "
                       "discard the rest of it.")
        return False
    full[TX_NOTICE_DISMISSED_KEY] = bool(dismissed)

    return _atomic_write_config(full, "the transcription-notice dismissal")


def active_outputs(settings: dict) -> list[str]:
    """Return the list of enabled output kinds, e.g. ['url', 'mp3', 'txt'].

    Order is the DISPLAY order (shortcut first, then video, audio, transcript,
    subtitles) and is load-bearing: it reaches the user as the badge order in
    the sync review and confirm screens via ``panopto.sync_plan.wanted_kinds``.
    """
    out = []
    if settings.get("output_url"):
        out.append("url")
    if settings.get("output_mp4"):
        out.append("mp4")
    if settings.get("output_mp3"):
        out.append("mp3")
    if settings.get("output_txt"):
        out.append("txt")
    if settings.get("output_srt"):
        out.append("srt")
    return out


def wants_transcription(settings: dict) -> bool:
    """True if any transcription output (txt/srt) is requested."""
    return bool(settings.get("output_txt") or settings.get("output_srt"))


# ── Per-run contract <-> runtime settings ───────────────────────────────────
# As of the "integrate Panopto like every other download" pivot, the OUTPUT
# choices (mp4/mp3/txt/srt) and the folder LAYOUT are per-run, configured in the
# download settings page (Section 4) and stored - exactly like the Canvas
# Content "secondary_content_contract" - in each synced folder's manifest. They
# are NOT persisted to the global Panopto JSON.
#
# The ENGINE config (model/language/device) is the one genuine one-time setup
# (you download a model once; it lives on disk). That alone still lives in the
# persisted JSON and is edited by the transcription-config dialog.
#
# A "contract" is the per-run portion: {output_mp4, output_mp3, output_txt,
# output_srt, layout}. ``compose_settings`` rehydrates a full settings dict by
# layering the contract over the persisted engine config, deriving ``enabled``.

_OUTPUT_KEYS = ("output_url", "output_mp4", "output_mp3", "output_txt", "output_srt")
_CONTRACT_KEYS = (*_OUTPUT_KEYS, "layout")
_ENGINE_KEYS = ("model", "language", "device")

# The session-state keys the download settings page writes its Section 4 choices
# to (``persistent_`` + these on Confirm). Paired with the contract key they
# feed, so "read the user's Panopto choices" is ONE mapping instead of the five
# hand-written copies that used to sit in app.py, sync_ui.py, sync/analysis.py
# and ui/sync_dialogs.py - four of which had to be found and edited to add a
# single output, and any one of which could be missed with no symptom but a
# format the user selected quietly never being produced.
_UI_OUTPUT_KEYS = {
    "output_url": "pan_out_url",
    "output_mp4": "pan_out_mp4",
    "output_mp3": "pan_out_mp3",
    "output_txt": "pan_out_txt",
    "output_srt": "pan_out_srt",
}


def engine_settings() -> dict:
    """Return only the persisted engine config (model/language/device)."""
    s = load_settings()
    return {k: s.get(k, PANOPTO_DEFAULTS[k]) for k in _ENGINE_KEYS}


def make_contract(*, mp4: bool, mp3: bool, txt: bool, srt: bool,
                  layout: str, url: bool = False) -> dict:
    """Build the per-run contract dict from individual output toggles + layout.

    ``url`` (the Shortcut output) defaults to False so a stored contract written
    before it existed rehydrates unchanged. Live call sites pass it explicitly -
    ``contract_from_ui_state`` is the one that reads the user's actual choices.
    """
    return {
        "output_url": bool(url),
        "output_mp4": bool(mp4),
        "output_mp3": bool(mp3),
        "output_txt": bool(txt),
        "output_srt": bool(srt),
        "layout": layout if layout in ("match", "separate") else "match",
    }


def contract_from_ui_state(state, *, prefix: str = "persistent_") -> dict:
    """Build a contract from the download page's Section 4 session keys.

    *state* is any mapping (``st.session_state`` in the app), read through
    ``prefix`` + the ``pan_out_*`` / ``pan_layout`` names. A missing key reads as
    False, which is the correct answer for these: they are session-only and
    reset at every app launch (see ``core.state_registry``).

    This exists because the same dict was hand-written at five call sites - the
    download run, the sync analysis, the sync list, the pair dialog and the
    transcription highlight - each one an independent chance to omit an output.
    Keep it the only place that maps a UI key to a contract key; it takes a
    mapping rather than importing Streamlit so this module stays UI-free.
    """
    def _get(name, default=False):
        try:
            return state.get(prefix + name, default)
        except AttributeError:
            return default

    layout = _get("pan_layout", "match")
    return make_contract(
        url=bool(_get(_UI_OUTPUT_KEYS["output_url"])),
        mp4=bool(_get(_UI_OUTPUT_KEYS["output_mp4"])),
        mp3=bool(_get(_UI_OUTPUT_KEYS["output_mp3"])),
        txt=bool(_get(_UI_OUTPUT_KEYS["output_txt"])),
        srt=bool(_get(_UI_OUTPUT_KEYS["output_srt"])),
        layout=layout if layout in ("match", "separate") else "match",
    )


def infer_contract_from_manifest(manifest: dict | None) -> dict | None:
    """Reconstruct a contract from Panopto artifacts already on disk.

    Recovery path for a folder whose stored ``panopto_contract`` is missing. That
    happens when the download-mode seed write fails (it is a best-effort
    ``_save_metadata``), and the consequence used to be severe and silent: sync
    fell back to the ``persistent_pan_out_*`` session toggles, which are
    session-only and reset to False on every app launch, so ``is_enabled()``
    returned False and the entire Panopto pass was skipped on every future sync.
    The user's Panopto setup appeared to have vanished, with no message.

    A folder that already contains produced artifacts is proof that Panopto WAS
    configured for it, which makes the all-False fallback provably wrong. The
    kinds present tell us which outputs were wanted, and a recorded path under
    "Panopto Recordings/" tells us the layout.

    Args:
        manifest: ``{video_id: {kind: rel_path}}`` from
            ``SyncManager.get_panopto_manifest()``.

    Returns:
        A contract dict, or ``None`` when the manifest is empty (nothing to infer
        from - a folder that never had Panopto must stay disabled).
    """
    if not manifest:
        return None

    kinds: set[str] = set()
    separate = False
    for per_video in manifest.values():
        if not isinstance(per_video, dict):
            continue
        for kind, rel in per_video.items():
            if kind in ("url", "mp4", "mp3", "txt", "srt"):
                kinds.add(kind)
            if isinstance(rel, str) and "panopto recordings/" in rel.replace("\\", "/").lower():
                separate = True

    if not kinds:
        return None

    # A transcript on disk implies the audio step ran, but the user may have since
    # had mp3 output turned off - only assert what the artifacts actually show.
    return make_contract(
        url="url" in kinds,
        mp4="mp4" in kinds,
        mp3="mp3" in kinds,
        txt="txt" in kinds,
        srt="srt" in kinds,
        layout="separate" if separate else "match",
    )


def extract_contract(settings: dict) -> dict:
    """Return the per-run (contract) portion of a full settings dict, for storage."""
    return {k: settings.get(k, PANOPTO_DEFAULTS[k]) for k in _CONTRACT_KEYS}


def compose_settings(contract: dict | None) -> dict:
    """Rehydrate a complete settings dict from a per-run *contract*.

    Engine config (model/language/device) is pulled from the persisted JSON;
    the output/layout come from the contract; ``enabled`` is derived from
    whether any output ends up selected.

    **A None/empty contract does NOT yield a disabled config** - it yields the
    defaults, and ``PANOPTO_DEFAULTS`` has mp3/txt/srt ON, so ``enabled`` comes
    back True. (This docstring claimed the opposite until 2026-07-30; the
    behaviour has always been this.) Keys absent from a partial contract are
    likewise filled from the defaults, not from False.

    That matters because ``panopto/runner.py`` resolves a target's outputs as
    ``target.get("settings") or settings``, so a target with a falsy contract
    inherits whatever this returned for the batch. Nothing reaches that state
    today - ``sync_ui`` skips any pair with no user-selected recordings, and the
    only path that yields an empty contract (a Panopto analysis that raised)
    also yields nothing to select - but it is one guard away, and the failure
    would be transcription nobody asked for. Every contract this module builds
    (``make_contract``, ``extract_contract``, ``infer_contract_from_manifest``)
    carries all five keys, so hardening the gaps to False would change only the
    None/empty/partial cases. Covered both ways in tests/test_panopto_settings.py.
    """
    s = dict(PANOPTO_DEFAULTS)
    s.update(engine_settings())
    for k in _CONTRACT_KEYS:
        if contract and k in contract:
            s[k] = contract[k]
    s["enabled"] = any(s.get(k) for k in _OUTPUT_KEYS)
    return s


def is_enabled(contract: dict | None) -> bool:
    """True if a contract selects at least one output kind.

    A question about the CONTRACT alone - it deliberately knows nothing about the
    global switch, because several callers ask it in order to DISPLAY what a
    folder or preset is configured for. Anything deciding what a RUN will do must
    ask :func:`effective_contract` first. See its docstring for why the two are
    separate.
    """
    return bool(contract) and any(contract.get(k) for k in _OUTPUT_KEYS)


def effective_contract(stored: dict | None) -> dict | None:
    """What a run will ACTUALLY do with *stored*, once the global switch applies.

    Returns *stored* unchanged while Panopto is on, and an all-outputs-off
    contract while it is off. Every execution entry point resolves through this;
    every DISPLAY surface keeps reading *stored* (see ``contract_to_ui_keys``).

    **Stored vs effective is the whole point.** A folder's ``panopto_contract``,
    a preset's ``pan_out_*`` and Section 4's session toggles are all statements
    about what the user CONFIGURED. The global switch is a statement about what
    should happen NEXT. Conflating them is why the switch used to be almost
    cosmetic: ``is_enabled(stored)`` was the only gate on the download phase
    (``app.py:_next_phase_after_courses``) and the sync discovery pass
    (``sync/analysis.py``), so switching Panopto off left both running - the
    Settings tooltip promised "the search is skipped entirely" while a Custom
    Download still fetched every recording. Only the Today daily sync honoured
    it, and only because ``core/auto_sync.py`` sets the run-scoped decline flag.

    **Turning Panopto off must never rewrite the past**, which is why this
    returns a value instead of mutating anything:

    * A folder's stored contract stays exactly as it was, so turning the switch
      back on resumes recordings with the outputs the user originally chose.
    * The user's Section 4 selections (``persistent_pan_out_*``) are untouched -
      zeroing them would silently discard the card's state on a preference flip.

    **Where the gate goes is load-bearing, not a style choice.** It must sit at
    or ABOVE the phase trigger, never only inside ``panopto.runner``: the
    download-mode phase seeds the folder's ``panopto_contract`` (``app.py``,
    "Persist this run's contract") BEFORE it calls the batch, and
    ``sync_ui`` only ever seeds ``if ... is None``, so a download run is the one
    thing that can overwrite it. A runner-only guard would therefore let the
    phase start, write an all-off contract over every folder it touched, and turn
    a reversible preference into permanent per-folder data loss.

    For the same reason this is NOT folded into ``compose_settings`` or
    ``is_enabled``: the first is what ``extract_contract`` seeds from, and the
    second is asked by display code (the ignored-recordings dialog resolves which
    output kinds count as "configured" through it - forcing them off there would
    render every ignored recording as unconfigured).
    """
    if is_globally_enabled():
        return stored
    return make_contract(
        url=False, mp4=False, mp3=False, txt=False, srt=False,
        layout=(stored or {}).get("layout", "match"),
    )


def contract_to_ui_keys(contract: dict | None) -> dict:
    """Map a per-run contract ({output_mp4..., layout}) to the badge/UI key
    names ({pan_out_mp4..., pan_layout}) consumed by the shared configuration
    summary renderer (``ui_shared.render_config_summary_badges``).

    Single source of truth so every config viewer (sync hub, dialogs) can show
    Panopto pills from a stored contract without re-deriving the mapping.
    """
    c = contract or {}
    layout = c.get("layout", "match")
    return {
        "pan_out_url": bool(c.get("output_url")),
        "pan_out_mp4": bool(c.get("output_mp4")),
        "pan_out_mp3": bool(c.get("output_mp3")),
        "pan_out_txt": bool(c.get("output_txt")),
        "pan_out_srt": bool(c.get("output_srt")),
        "pan_layout": layout if layout in ("match", "separate") else "match",
    }
