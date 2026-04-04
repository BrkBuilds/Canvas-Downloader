import platform
import plistlib
from pathlib import Path

def compile_urls_to_txt(course_dir: str | Path, course_name: str) -> tuple[Path | None, list[Path]]:
    """
    Scans a course directory for shortcut files (.url on Windows, .webloc on macOS),
    extracts the links, and compiles them into a single NotebookLM_External_Links.txt
    file in the course root. Uses a Merge-Append strategy to preserve existing links.
    """
    course_path = Path(course_dir)

    # Platform-aware glob: .webloc on macOS, .url on Windows
    if platform.system() == 'Darwin':
        shortcut_files = list(course_path.rglob("*.webloc"))
    else:
        shortcut_files = list(course_path.rglob("*.url"))
    
    if not shortcut_files:
        return None, []
        
    output_path = course_path / "NotebookLM_External_Links.txt"
    
    existing_urls = set()
    existing_content = ""
    
    # 1. State Hydration
    if output_path.exists():
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()
            for line in existing_content.splitlines():
                if line.startswith("🔗 "):
                    # Robust hydration parsing: aggressive strip
                    existing_urls.add(line[2:].strip())
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not read existing NotebookLM text file for deduplication: {e}")

    compiled_links = []
    processed_shortcuts = []
    
    # 2. Deduplication
    for shortcut_file in shortcut_files:
        raw_link = _extract_url(shortcut_file)
        if raw_link:
            link = raw_link.strip()
            # We always add it to processed_shortcuts so it gets physically deleted by the post-processor!
            processed_shortcuts.append(shortcut_file)
            
            if link not in existing_urls:
                compiled_links.append(f"📌 {shortcut_file.stem}\n🔗 {link}\n")
                existing_urls.add(link)
                
    if not compiled_links:
        # If nothing new to append but we still found shortcuts (duplicates), return them for unlinking
        if processed_shortcuts:
            return (output_path if existing_content else None), processed_shortcuts
        return None, []
        
    # 3. Append/Rewrite
    write_mode = 'a' if existing_content else 'w'
    
    if not existing_content:
        # Build a beautiful, copy-paste friendly output header
        output_content = (
            f"========================================================\n"
            f" 🤖 NotebookLM Links for: {course_name}\n"
            f"========================================================\n"
            f"Copy and paste these links directly into NotebookLM's website source field.\n\n"
        )
    else:
        # Add a newline spacer if we are appending to an existing master list
        output_content = "\n"

    output_content += "\n".join(compiled_links)
    
    with open(output_path, write_mode, encoding='utf-8') as f:
        f.write(output_content)
        
    return output_path, processed_shortcuts


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
