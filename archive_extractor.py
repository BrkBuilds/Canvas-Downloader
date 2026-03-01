import os
import zipfile
import tarfile
from pathlib import Path

def extract_and_stub(archive_path: str | Path) -> str | None:
    abs_archive = Path(archive_path).resolve().absolute()
    
    # Determine the extraction folder name (strip .zip or .tar.gz)
    if abs_archive.name.lower().endswith('.tar.gz'):
        extract_dir = abs_archive.with_name(abs_archive.name[:-7])
    else:
        extract_dir = abs_archive.with_suffix('')
        
    # The 0-byte ghost stub that will trick the database
    stub_path = abs_archive.with_name(abs_archive.name + ".extracted")
    
    try:
        # Create extraction directory
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract based on type
        if abs_archive.suffix.lower() == '.zip':
            with zipfile.ZipFile(abs_archive, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif abs_archive.name.lower().endswith(('.tar.gz', '.tar')):
            with tarfile.open(abs_archive, 'r:*') as tar_ref:
                tar_ref.extractall(extract_dir)
        else:
            return None
            
        # 1. Delete the heavy original archive
        abs_archive.unlink(missing_ok=True)
        
        # 2. Create the 0-byte Ghost Stub
        stub_path.touch()
        
        return str(stub_path)
        
    except Exception as e:
        print(f"Failed to extract {abs_archive.name}: {e}")
        return None
