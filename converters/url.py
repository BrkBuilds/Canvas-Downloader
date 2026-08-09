from pathlib import Path

from shared.shortcuts import read_shortcut, shortcut_extension

def compile_urls_to_txt(course_dir: str | Path, course_name: str) -> tuple[Path | None, list[Path]]:
    """
    Scans a course directory for shortcut files (.url and .webloc, both platforms),
    extracts the links, and compiles them into a single Compiled_External_Links.txt
    file in the course root. Uses a Merge-Append strategy to preserve existing links.

    Returns ``(compiled_path_or_None, consumable_shortcuts)``. Only shortcuts in
    THIS platform's own format appear in the second list - the caller deletes
    them. See the comment on the glob below.
    """
    course_path = Path(course_dir)

    # READ both formats, DELETE only this platform's own.
    #
    # A course folder is not tied to one OS: `shared.shortcuts` handles `.url`
    # and `.webloc` together for exactly that reason, and the Panopto Shortcut
    # output deliberately adopts a link written on the other platform rather than
    # duplicating it. This function globbed a single suffix, so a folder synced on
    # Windows and later opened on a Mac had every external link silently left out
    # of the compilation.
    #
    # The asymmetry is deliberate. Reading the other platform's shortcut only ever
    # ADDS a link to the compiled text - a pure gain, and reversible. Deleting one
    # is not: this loop's caller removes everything it returns in
    # `processed_shortcuts`, so consuming a `.webloc` on Windows would destroy a
    # file that machine cannot even open to check, on behalf of a user who is
    # probably still using it on their Mac. Compile widely, delete narrowly.
    _own = shortcut_extension().lower()
    shortcut_files = [p for pattern in ("*.url", "*.webloc")
                      for p in course_path.rglob(pattern)]


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
                if line.lower().startswith("http"):
                    # Robust hydration parsing: aggressive strip; lowercase for case-insensitive dedup
                    existing_urls.add(line.strip().lower())
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not read existing NotebookLM text file for deduplication: {e}")

    compiled_links = []
    processed_shortcuts = []
    
    # 2. Deduplication
    for shortcut_file in shortcut_files:
        raw_link, produced_by = read_shortcut(shortcut_file)

        # An app-PRODUCED shortcut is an output the user asked for, not a Canvas
        # link waiting to be gathered up. This loop's caller deletes everything
        # it returns in ``processed_shortcuts``, so without this check the
        # Panopto Shortcut output would be compiled away and deleted on every
        # single run - and, because the folder's panopto manifest still recorded
        # it, the next sync would dutifully restore it so the next compilation
        # could delete it again. Endless churn, one "restored" line per
        # recording per run, and never a link left on disk.
        if produced_by:
            continue

        if raw_link:
            link = raw_link.strip()

            # Guard against malformed or non-web URLs (e.g. javascript:, file:, data:)
            # that could cause harm if pasted into a browser or AI tool.
            # These are NOT added to processed_shortcuts: deleting the shortcut
            # without compiling its link would destroy the user's only copy.
            if not (link.startswith('http://') or link.startswith('https://')):
                continue

            # Web link captured (new or already-compiled duplicate) → the
            # shortcut file is safe to delete by the post-processor - but ONLY if
            # it is this platform's own format. The other platform's shortcut is
            # read for its link and then left exactly where it was.
            if shortcut_file.suffix.lower() == _own:
                processed_shortcuts.append(shortcut_file)

            if link.lower() not in existing_urls:
                compiled_links.append(f"📌 {shortcut_file.stem}\n{link}\n")
                existing_urls.add(link.lower())
                
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
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(full_content)
            f.flush()
            try:
                _os.fsync(f.fileno())
            except OSError:
                pass
        _os.replace(str(tmp_path), str(output_path))
    except OSError:
        # Clean up orphaned temp file on failure so it doesn't pollute the folder
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise

    return output_path, processed_shortcuts


# The reader used to live here as ``_extract_url``. It now comes from
# ``shared.shortcuts`` alongside the WRITER, because this module deletes what it
# reads: whether a shortcut may be consumed is a property of how it was written,
# and two implementations of one file format is how that answer drifts. The
# shared reader is also long-path safe and never raises.
