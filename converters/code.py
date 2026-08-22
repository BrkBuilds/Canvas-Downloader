import os
import shutil
import logging
from pathlib import Path
from shared.helpers import make_long_path, path_exists

logger = logging.getLogger(__name__)

# Top 50 code/data extensions for students (EXCLUDING .html, which is handled by the MD converter)
CODE_EXTENSIONS = {
    # Programming Languages
    '.py', '.java', '.c', '.cpp', '.cs', '.h', '.hpp', '.js', '.jsx', '.ts', '.tsx', 
    '.css', '.scss', '.php', '.rb', '.swift', '.go', '.rs', '.kt', '.scala', 
    '.sh', '.bash', '.zsh', '.bat', '.ps1', '.pl', '.pm', '.r', '.rmd', '.m', '.sql', 
    '.dart', '.lua', '.asm', '.vba',
    # Data & Config
    '.csv', '.tsv', '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', 
    '.env', '.log', '.mdx', '.vue', '.svelte'
}

def convert_code_to_txt(file_path: str | Path, dst=None) -> str | None:
    """
    Converts a code/data file to a .txt file by renaming the extension to _ext.txt
    and prepending a header. It explicitly writes in UTF-8 and deletes the original file.

    *dst* overrides the destination. The caller passes one so this converter goes
    through the same collision/ownership resolver as every other - without it,
    a re-conversion wrote straight over a .txt the student had annotated.

    Returns the absolute path of the new .txt file as a string if successful, else None.
    """
    original_path = Path(file_path)

    # Check if the suffix is in our supported list
    if original_path.suffix.lower() not in CODE_EXTENSIONS:
        return None

    # Construct new name: filename.py -> filename_py.txt
    clean_suffix = original_path.suffix.replace('.', '_')
    new_name = f"{original_path.stem}{clean_suffix}.txt"
    txt_path = Path(dst) if dst is not None else original_path.with_name(new_name)
    
    try:
        # Read the original file safely, replacing bad characters
        with open(make_long_path(original_path), 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # Add a small header so NotebookLM knows what this is
        header = f"--- Original File: {original_path.name} ---\n\n"

        # Write to the new .txt file forcing UTF-8 encoding, then fsync so the
        # data is durable on disk before we delete the original.  Without
        # fsync a power-loss between close() and unlink() can lose the file.
        with open(make_long_path(txt_path), 'w', encoding='utf-8') as f:
            f.write(header + content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        # Verify the output exists and is non-empty before deleting the source.
        # file_has_content, not a hand-rolled size check: it is the shared gate
        # the whole delete family uses, it is already long-path safe, and it
        # reports WHY - which a bare `== 0` cannot. tests/test_crash_vector_
        # hardening.py counts these, so a private spelling reads as no gate.
        from converters.verify import file_has_content
        _ok, _why = file_has_content(txt_path, what="text file")
        if not _ok:
            logger.error(
                f"Code converter reported success for {original_path.name} "
                f"but {_why}; keeping original file."
            )
            return None

        # Delete the original code file
        Path(make_long_path(original_path)).unlink(missing_ok=True)

        return str(txt_path)
    except Exception as e:
        logger.error(f"Failed to convert code file {original_path.name}: {e}")
        # Clean up a partial .txt if the write started but failed mid-way.
        try:
            if path_exists(txt_path) and os.path.getsize(make_long_path(txt_path)) == 0:
                Path(make_long_path(txt_path)).unlink(missing_ok=True)
        except OSError:
            pass
        return None
