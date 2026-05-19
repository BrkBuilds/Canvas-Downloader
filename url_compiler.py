import platform
from pathlib import Path

def compile_urls_to_txt(course_dir: str | Path, course_name: str) -> tuple[Path | None, list[Path]]:
    """
    Scans a course directory for shortcut files (.url on Windows, .webloc on macOS),
    extracts the links, and compiles them into a single Compiled_External_Links.txt
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
        
    output_path = course_path / "Compiled_External_Links.txt"
    
    existing_urls = set()
    existing_content = ""
    
    # 1. State Hydration
    if output_path.exists():
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()
            for line in existing_content.splitlines():
                if line.startswith("http"):
                    # Robust hydration parsing: aggressive strip
                    existing_urls.add(line.strip())
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

            # Guard against malformed or non-web URLs (e.g. javascript:, file:, data:)
            # that could cause harm if pasted into a browser or AI tool.
            if not (link.startswith('http://') or link.startswith('https://')):
                continue

            if link not in existing_urls:
                compiled_links.append(f"📌 {shortcut_file.stem}\n{link}\n")
                existing_urls.add(link)
                
    if not compiled_links:
        # No new links found (all duplicates or no shortcuts). Return None for the
        # compiled path so callers don't log a false success (M-27). Shortcuts are
        # still returned so callers can clean them up.
        return None, processed_shortcuts
        
    # 3. Atomic rewrite: assemble the full new file content, write to .tmp,
    #    then os.replace so a mid-write crash never corrupts the output file.
    import os as _os

    if not existing_content:
        header = (
            f"========================================================\n"
            f" 🤖 Compiled Links for: {course_name}\n"
            f"========================================================\n"
            f"Copy and paste these links directly into your preferred AI tool - e.g. NotebookLM.\n\n"
        )
        full_content = header + "\n".join(compiled_links)
    else:
        # Preserve existing content and append new links after a blank line spacer
        full_content = existing_content + "\n" + "\n".join(compiled_links)

    tmp_path = output_path.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(full_content)
    _os.replace(str(tmp_path), str(output_path))

    return output_path, processed_shortcuts


def _extract_url(shortcut_file: Path) -> str | None:
    """Extract URL from a .url (Windows INI) or .webloc (macOS plist) file."""
    if shortcut_file.suffix.lower() == '.webloc':
        try:
            import plistlib
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
