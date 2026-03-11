import os
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
            with zipfile.ZipFile(abs_archive, 'r') as zip_ref:
                uncompressed_size = sum(info.file_size for info in zip_ref.infolist())
                if uncompressed_size > MAX_UNCOMPRESSED_SIZE or (archive_size > 0 and (uncompressed_size / archive_size) > MAX_COMPRESSION_RATIO):
                    raise Exception(f"Zip bomb detected (Ratio: {uncompressed_size/archive_size:.1f}, Size: {uncompressed_size/(1024**3):.1f}GB).")
                zip_ref.extractall(extract_dir)
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
