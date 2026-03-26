import os
import sys
import zipfile
import tarfile
from pathlib import Path

MAX_UNCOMPRESSED_SIZE = 50 * 1024 * 1024 * 1024  # 50 GB
MAX_COMPRESSION_RATIO = 100.0

def extract_and_stub(archive_path: str | Path) -> str | None:
    abs_archive = Path(archive_path).resolve().absolute()
    
    # Windows MAX_PATH protection for the extraction process
    if os.name == 'nt' and not str(abs_archive).startswith('\\\\?\\'):
        abs_archive = Path('\\\\?\\' + str(abs_archive))
    
    # Determine the extraction folder name (strip .zip or .tar.gz)
    if abs_archive.name.lower().endswith('.tar.gz'):
        extract_dir = abs_archive.with_name(abs_archive.name[:-7])
    else:
        extract_dir = abs_archive.with_suffix('')
        
    # The 0-byte ghost stub that will trick the database
    stub_path = abs_archive.with_name(abs_archive.name + ".extracted")
    
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
                    uncompressed_size = sum(info.file_size for info in zip_ref.infolist())
                    if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                        raise Exception(f"Zip bomb detected (Ratio: {uncompressed_size/archive_size:.1f}, Size: {uncompressed_size/(1024**3):.1f}GB).")
                    zip_ref.extractall(extract_dir)
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
                    uncompressed_size = sum(info.file_size for info in mutated_members)
                    if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                        raise Exception(f"Zip bomb detected (Ratio: {uncompressed_size/archive_size:.1f}, Size: {uncompressed_size/(1024**3):.1f}GB).")
                    zip_ref.extractall(path=extract_dir, members=mutated_members)
        elif abs_archive.name.lower().endswith(('.tar.gz', '.tar')):
            mode = 'r:gz' if abs_archive.name.lower().endswith('.gz') else 'r:'
            with tarfile.open(abs_archive, mode) as tar_ref:
                uncompressed_size = sum(info.size for info in tar_ref.getmembers() if info.isfile())
                if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                    raise Exception(f"Archive bomb detected (Ratio: {uncompressed_size/archive_size:.1f}, Size: {uncompressed_size/(1024**3):.1f}GB).")
                
                # Mitigation for CVE-2007-4559 (tarfile path traversal)
                if hasattr(tarfile, 'data_filter'):
                    tar_ref.extractall(extract_dir, filter='data')
                else:
                    # Manual path traversal guard for Python < 3.12
                    resolved_target = str(extract_dir.resolve())
                    for member in tar_ref.getmembers():
                        member_path = str((extract_dir / member.name).resolve())
                        if not member_path.startswith(resolved_target):
                            raise Exception(f"Blocked path traversal attempt in tar: {member.name}")
                    tar_ref.extractall(extract_dir)
        else:
            return None
            
        # 1. Delete the heavy original archive
        abs_archive.unlink(missing_ok=True)
        
        # 2. Create the 0-byte Ghost Stub
        stub_path.touch()
        
        return str(stub_path)
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to extract {abs_archive.name}: {e}")
        return None
