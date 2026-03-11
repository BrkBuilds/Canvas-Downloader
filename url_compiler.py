import os
import platform
import plistlib
from pathlib import Path

def compile_urls_to_txt(course_dir: str | Path, course_name: str) -> Path | None:
    """
    Scans a course directory for shortcut files (.url on Windows, .webloc on macOS),
    extracts the links, and compiles them into a single NotebookLM_External_Links.txt
    file in the course root.
    """
    course_path = Path(course_dir)

    # Platform-aware glob: .webloc on macOS, .url on Windows
    if platform.system() == 'Darwin':
        shortcut_files = list(course_path.rglob("*.webloc"))
    else:
        shortcut_files = list(course_path.rglob("*.url"))
    
    if not shortcut_files:
        return None
        
    compiled_links = []
    
    for shortcut_file in shortcut_files:
        link = _extract_url(shortcut_file)
        if link:
            compiled_links.append(f"📌 {shortcut_file.stem}\n🔗 {link}\n")
            
    if not compiled_links:
        return None
        
    # Build a beautiful, copy-paste friendly output
    output_content = (
        f"========================================================\n"
        f" 🤖 NotebookLM Links for: {course_name}\n"
        f"========================================================\n"
        f"Copy and paste these links directly into NotebookLM's website source field.\n\n"
    )
    output_content += "\n".join(compiled_links)
    
    # Save in the root of the course directory
    output_path = course_path / "NotebookLM_External_Links.txt"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output_content)
        
    return output_path


def _extract_url(shortcut_file: Path) -> str | None:
    """Extract URL from a .url (Windows INI) or .webloc (macOS plist) file."""
    if shortcut_file.suffix.lower() == '.webloc':
        try:
            with open(shortcut_file, 'rb') as f:
                plist = plistlib.load(f)
                return plist.get('URL', None)
        except Exception:
            import logging
            logging.getLogger(__name__).error(f"Failed to parse webloc: {shortcut_file.name}")
            return None
    else:
        # Windows .url INI format
        try:
            with open(shortcut_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.strip().upper().startswith("URL="):
                        return line.strip()[4:]
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to read {shortcut_file.name}: {e}")
        return None
