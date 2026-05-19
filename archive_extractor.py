import os
import sys
import zipfile
import tarfile
from pathlib import Path

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

def extract_archive(archive_path: str | Path) -> bool | None:
    # Do NOT apply \\?\ to abs_archive — tarfile.open() rejects it on Python < 3.12.
    # The archive file itself won't hit MAX_PATH; only extracted contents can.
    abs_archive = Path(archive_path).resolve().absolute()

    # Determine the extraction folder name (strip .zip or .tar.gz)
    if abs_archive.name.lower().endswith('.tar.gz'):
        extract_dir = abs_archive.with_name(abs_archive.name[:-7])
    else:
        extract_dir = abs_archive.with_suffix('')

    # Apply long-path prefix only to the extraction directory so that deeply
    # nested members don't silently fail on Windows MAX_PATH (260 chars).
    if os.name == 'nt' and not str(extract_dir).startswith('\\\\?\\'):
        extract_dir = Path('\\\\?\\' + str(extract_dir))
        

    
    try:
        archive_size = abs_archive.stat().st_size
        
        # Create extraction directory
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract based on type (with Zip Bomb protection)
        if abs_archive.suffix.lower() == '.zip':
            # ── UTF-8 filename fix for non-ASCII characters (e.g. Danish ø, æ, å) ──
            # Python's zipfile defaults to CP437 decoding unless the UTF-8 flag
            # (bit 11) is set. Many tools (including Canvas LMS) don't set this flag.
            if sys.version_info >= (3, 11):
                # Python 3.11+ natively supports metadata_encoding
                with zipfile.ZipFile(abs_archive, 'r', metadata_encoding='utf-8') as zip_ref:
                    members = _filter_zip_members(zip_ref.infolist())
                    uncompressed_size = sum(info.file_size for info in members)
                    if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                        raise Exception(f"Zip bomb detected (Ratio: {uncompressed_size/archive_size:.1f}, Size: {uncompressed_size/(1024**3):.1f}GB).")
                    zip_ref.extractall(extract_dir, members=members)
            else:
                # Python < 3.11: manually re-decode CP437 → UTF-8
                with zipfile.ZipFile(abs_archive, 'r') as zip_ref:
                    mutated_members = []
                    for info in zip_ref.infolist():
                        # Only re-decode if the UTF-8 flag (bit 11) is NOT set
                        if info.flag_bits & 0x800 == 0:
                            try:
                                info.filename = info.filename.encode('cp437').decode('utf-8')
                            except (UnicodeDecodeError, UnicodeEncodeError):
                                pass  # Keep original if re-encoding fails
                        mutated_members.append(info)
                    mutated_members = _filter_zip_members(mutated_members)
                    uncompressed_size = sum(info.file_size for info in mutated_members)
                    if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                        raise Exception(f"Zip bomb detected (Ratio: {uncompressed_size/archive_size:.1f}, Size: {uncompressed_size/(1024**3):.1f}GB).")
                    zip_ref.extractall(path=extract_dir, members=mutated_members)
        elif abs_archive.name.lower().endswith(('.tar.gz', '.tar')):
            mode = 'r:gz' if abs_archive.name.lower().endswith('.gz') else 'r:'
            with tarfile.open(abs_archive, mode) as tar_ref:
                # Cache members once — streaming .tar.gz archives cannot rewind,
                # so a second getmembers() call would return an empty list.
                tar_members = tar_ref.getmembers()
                uncompressed_size = sum(info.size for info in tar_members if info.isfile())
                if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                    raise Exception(f"Archive bomb detected (Ratio: {uncompressed_size/archive_size:.1f}, Size: {uncompressed_size/(1024**3):.1f}GB).")

                # Mitigation for CVE-2007-4559 (tarfile path traversal)
                if hasattr(tarfile, 'data_filter'):
                    tar_ref.extractall(extract_dir, filter='data')
                else:
                    # Python < 3.12: manual path traversal + symlink guard
                    resolved_target = str(extract_dir.resolve())
                    for member in tar_members:
                        member_path = str((extract_dir / member.name).resolve())
                        if not member_path.startswith(resolved_target):
                            raise Exception(f"Blocked path traversal attempt in tar: {member.name}")
                        if member.issym() or member.islnk():
                            link_dir = (extract_dir / member.name).parent.resolve()
                            link_path = str((link_dir / member.linkname).resolve())
                            if not link_path.startswith(resolved_target):
                                raise Exception(f"Blocked symlink traversal in tar: {member.name} -> {member.linkname}")
                    tar_ref.extractall(extract_dir, members=tar_members)
        else:
            return None
            
        # Delete the heavy original archive (Sync Engine Bypass handles the missing file)
        abs_archive.unlink(missing_ok=True)
        
        return True
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to extract {abs_archive.name}: {e}")
        return None
