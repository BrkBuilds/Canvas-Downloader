import logging
import os
import zipfile
import tarfile
from pathlib import Path

from shared.helpers import make_long_path, path_exists

# Module level, NOT inside the except handler where it used to live: a function
# that does `import logging` anywhere in its body makes `logging` a LOCAL name
# for the WHOLE function, so any earlier reference raises UnboundLocalError -
# silently, because the surrounding handler catches it and reports the wrong
# reason. Same trap as the `isolate` bug in core/canvas_logic.py.
logger = logging.getLogger(__name__)

MAX_UNCOMPRESSED_SIZE = 50 * 1024 * 1024 * 1024  # 50 GB
MAX_COMPRESSION_RATIO = 100.0


def _filter_zip_members(members):
    """Strip macOS metadata entries from a zip member list.

    macOS-created zips contain a __MACOSX/ directory of AppleDouble resource
    fork files (._filename) alongside the real content.  These are invisible
    clutter on any non-macOS system and noise even on macOS.
    """
    return [
        m for m in members
        if not m.filename.startswith('__MACOSX/')
        and not os.path.basename(m.filename).startswith('._')
    ]

def _decline(extract_dir) -> bool:
    """Back out of an extraction we decided not to perform.

    The target folder is created before the archive's member list can be read,
    so a guard that simply returned would leave an empty folder next to the
    untouched archive - a stray directory the user did not ask for and the sync
    analyzer would have to reason about. Removed only when empty, so this can
    never delete a real extraction.
    """
    try:
        os.rmdir(make_long_path(extract_dir))
    except OSError:
        pass
    return False


def _ratio_txt(uncompressed: int, archive_size: int) -> str:
    """The compression ratio for the bomb message, or "?" when it cannot exist.

    THE GUARD IS ON THE CONDITION AND THE MESSAGE DIVIDED UNGUARDED. Both bomb
    checks read `archive_size > 0 and (uncompressed / archive_size) > RATIO`, but
    the `raise` beside them interpolated the same division with no guard - and the
    condition's OTHER clause (`uncompressed > MAX_UNCOMPRESSED_SIZE`) is true
    independently of `archive_size`. So the one line meant to EXPLAIN a declined
    archive could raise ZeroDivisionError instead, replacing "Zip bomb detected"
    with a crash in the same handler.

    Not reachable today - `archive_size` is a real `stat().st_size` and a 0-byte
    file cannot be parsed as a zip or a tar, so a populated member list implies a
    non-zero size. Kept because the shape is the trap, not this instance: the
    reachability argument depends on a fact two libraries away, and the fix costs
    one branch.
    """
    if not archive_size:
        return "?"
    return f"{uncompressed / archive_size:.1f}"


def extract_archive(archive_path: str | Path,
                    max_files: int | None = None) -> bool | None:
    """Extract one archive in place, into a folder named after it.

    Returns:
        ``True``  - extracted.
        ``False`` - DECLINED by the ``max_files`` guard. The archive is left
                    exactly as it was; nothing was written and nothing removed.
        ``None``  - unsupported type, or extraction failed.

    ``False`` and ``None`` are different answers and the caller must treat them
    differently: one is the app doing what it was told, the other is a failure.
    ``False`` was previously unused by this function, which is why it is free to
    carry the new meaning without disturbing any existing branch.

    ``max_files`` complements the bomb guard rather than duplicating it. That
    one measures uncompressed SIZE and compression RATIO, so an archive of very
    many very small files sails through: one real course unpacked 21,630 files,
    which is both a surprise and the source of the deepest paths in the folder.
    """
    # The archive is OPENED through a file object, not by path. Both of the
    # claims that used to stand here were wrong, and each was load-bearing:
    #
    #   "the archive file itself won't hit MAX_PATH" - measured 2026-08-22, a
    #   zip downloaded into a deep course folder sat at 280 characters and could
    #   not be opened at all, so extraction failed outright;
    #   "tarfile.open() rejects the prefix on Python < 3.12" - true once, and a
    #   version dependency this module has no reason to carry.
    #
    # A file object settles both: Python's own open() handles the prefix, and
    # zipfile/tarfile never see a path. `abs_archive` stays CLEAN because it is
    # what names the extraction folder, the log lines and the delete.
    abs_archive = Path(archive_path).resolve().absolute()
    abs_archive_lp = make_long_path(abs_archive)   # for OPENING only

    # Determine the extraction folder name (strip .zip or .tar.gz)
    if abs_archive.name.lower().endswith('.tar.gz'):
        extract_dir = abs_archive.with_name(abs_archive.name[:-7])
    else:
        extract_dir = abs_archive.with_suffix('')

    # Apply long-path prefix only to the extraction directory so that deeply
    # nested members don't silently fail on Windows MAX_PATH (260 chars).
    # Via the shared helper, NOT a hand-rolled concatenation: the prefix has to
    # take the "UNC\" form for a network share and needs backslash separators,
    # neither of which a bare "\\?\" + str(...) does.
    if os.name == 'nt':
        extract_dir = Path(make_long_path(extract_dir))
        

    
    try:
        archive_size = os.stat(make_long_path(abs_archive)).st_size
        
        # Create extraction directory
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract based on type (with Zip Bomb protection)
        if abs_archive.suffix.lower() == '.zip':
            # ── UTF-8 filename fix for non-ASCII characters (e.g. Danish ø, æ, å) ──
            # Python's zipfile defaults to CP437 decoding unless the UTF-8 flag (bit 11)
            # is set. Many tools (including Canvas LMS) don't set this flag even for
            # UTF-8 content. metadata_encoding='utf-8' in 3.11+ forces UTF-8 on ALL
            # entries, which corrupts legitimately CP437-encoded filenames. Instead we
            # always use the per-member flag approach: re-decode only untagged entries.
            with open(abs_archive_lp, 'rb') as _afh, \
                    zipfile.ZipFile(_afh, 'r') as zip_ref:
                mutated_members = []
                for info in zip_ref.infolist():
                    if info.flag_bits & 0x800 == 0:  # UTF-8 flag not set → try CP437→UTF-8
                        try:
                            info.filename = info.filename.encode('cp437').decode('utf-8')
                        except (UnicodeDecodeError, UnicodeEncodeError):
                            pass  # Keep original if re-encoding fails
                    mutated_members.append(info)
                members = _filter_zip_members(mutated_members)
                # Counted BEFORE the first write, so declining costs nothing and
                # leaves no half-extracted folder behind. Directory entries do
                # not count - the user's mental model is "how many files will
                # this put in my course folder".
                if max_files is not None:
                    _n_files = sum(1 for i in members if not i.is_dir())
                    if _n_files > max_files:
                        return _decline(extract_dir)
                uncompressed_size = sum(info.file_size for info in members)
                if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                    raise Exception(f"Zip bomb detected (Ratio: {_ratio_txt(uncompressed_size, archive_size)}, Size: {uncompressed_size/(1024**3):.1f}GB).")
                # Guard against zip slip: validate every member path resolves inside
                # extract_dir before extraction (mirrors the TAR guard below).
                # Use os.path.commonpath for a robust comparison that is correct
                # on Windows even when extract_dir carries the \\?\ long-path
                # prefix (a startswith() check on resolved strings is fragile
                # because Path.resolve() may strip or normalize the prefix
                # differently per call).
                resolved_root = os.path.normpath(str(extract_dir.resolve()))
                for info in members:
                    member_dest = os.path.normpath(str((extract_dir / info.filename).resolve()))
                    try:
                        common = os.path.commonpath([resolved_root, member_dest])
                    except ValueError:
                        # Different drives on Windows - definitely escaping
                        raise Exception(f"Blocked path traversal attempt in zip: {info.filename}")
                    if common != resolved_root:
                        raise Exception(f"Blocked path traversal attempt in zip: {info.filename}")
                    zip_ref.extract(info, path=extract_dir)
        elif abs_archive.name.lower().endswith(('.tar.gz', '.tar')):
            mode = 'r:gz' if abs_archive.name.lower().endswith('.gz') else 'r:'
            with open(abs_archive_lp, 'rb') as _afh, \
                    tarfile.open(fileobj=_afh, mode=mode) as tar_ref:
                # Cache members once - streaming .tar.gz archives cannot rewind,
                # so a second getmembers() call would return an empty list.
                tar_members = tar_ref.getmembers()
                if max_files is not None:
                    _n_files = sum(1 for i in tar_members if i.isfile())
                    if _n_files > max_files:
                        return _decline(extract_dir)
                uncompressed_size = sum(info.size for info in tar_members if info.isfile())
                if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                    raise Exception(f"Archive bomb detected (Ratio: {_ratio_txt(uncompressed_size, archive_size)}, Size: {uncompressed_size/(1024**3):.1f}GB).")

                # Mitigation for CVE-2007-4559 (tarfile path traversal)
                if hasattr(tarfile, 'data_filter'):
                    tar_ref.extractall(extract_dir, filter='data')
                else:
                    # Python < 3.12: manual path traversal + symlink guard
                    resolved_target = os.path.normpath(str(extract_dir.resolve()))
                    for member in tar_members:
                        member_path = os.path.normpath(str((extract_dir / member.name).resolve()))
                        try:
                            common = os.path.commonpath([resolved_target, member_path])
                        except ValueError:
                            raise Exception(f"Blocked path traversal attempt in tar: {member.name}")
                        if common != resolved_target:
                            raise Exception(f"Blocked path traversal attempt in tar: {member.name}")
                        if member.issym() or member.islnk():
                            link_dir = (extract_dir / member.name).parent.resolve()
                            link_path = os.path.normpath(str((link_dir / member.linkname).resolve()))
                            try:
                                lcommon = os.path.commonpath([resolved_target, link_path])
                            except ValueError:
                                raise Exception(f"Blocked symlink traversal in tar: {member.name} -> {member.linkname}")
                            if lcommon != resolved_target:
                                raise Exception(f"Blocked symlink traversal in tar: {member.name} -> {member.linkname}")
                    tar_ref.extractall(extract_dir, members=tar_members)
        else:
            return None
            
        # Delete the heavy original archive (Sync Engine Bypass handles the
        # missing file) - but ONLY once something actually came out of it.
        #
        # Both extraction paths can legitimately produce nothing while raising
        # nothing: _filter_zip_members strips every __MACOSX/ and ._* entry, and
        # tarfile's `data` filter SILENTLY SKIPS members it considers unsafe. An
        # archive whose entire content is filtered away therefore reached this
        # line with an empty folder, and deleted the user's only copy of the
        # archive to show for it.
        if not any(os.scandir(str(extract_dir))):
            logger.warning(
                "Extracted nothing from %s (every member was filtered or skipped); "
                "keeping the archive.", abs_archive.name)
            _decline(extract_dir)          # remove the empty folder we made
            return None

        Path(make_long_path(abs_archive)).unlink(missing_ok=True)

        return True
        
    except Exception as e:
        logger.error(f"Failed to extract {abs_archive.name}: {e}")
        # Same reasoning as _decline's: the target folder is created before the
        # member list can be read, so a guard that trips afterwards (a zip bomb,
        # a blocked path traversal) left an empty directory next to the
        # untouched archive - something the user did not ask for and the sync
        # analyzer then has to reason about. _decline uses os.rmdir, which
        # removes ONLY an empty directory, so a PARTIAL extraction that failed
        # halfway keeps everything it managed to write.
        try:
            _decline(extract_dir)
        except Exception:
            pass
        return None
