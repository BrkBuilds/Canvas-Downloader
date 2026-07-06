import os
import logging
from pathlib import Path
from bs4 import BeautifulSoup
import markdownify

logger = logging.getLogger(__name__)

def convert_html_to_md(html_path: Path | str, dst: Path | str | None = None) -> Path | None:
    """
    Converts an HTML file to Markdown, saving it with a .md extension
    in the same directory. Deletes the original HTML file on success.
    
    Args:
        html_path: Path to the .html file
        
    Returns:
        Path to the new .md file, or None if conversion failed.
    """
    try:
        html_path = Path(html_path)
        if not html_path.exists() or html_path.suffix.lower() != '.html':
            logger.warning(f"Invalid HTML file path: {html_path}")
            return None
            
        # H-7: honour an explicit target (ownership-resolved by the caller).
        md_path = Path(dst) if dst is not None else html_path.with_suffix('.md')
        
        # Enforce UTF-8 encoding for reading
        with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()
            
        # Parse HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # Strip script/style/noscript tags so they don't bleed as raw HTML into the .md output
        for tag in soup.find_all(['script', 'style', 'noscript']):
            tag.decompose()

        # Convert to Markdown
        md_content = markdownify.markdownify(str(soup), heading_style="ATX")

        # Enforce UTF-8 encoding for writing, then fsync so the data is
        # durable on disk before we delete the original HTML.  Without fsync
        # a power-loss between close() and remove() can lose the file.
        with open(md_path, 'w', encoding='utf-8', errors='replace') as f:
            f.write(md_content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        # Verify the output exists before deleting the source.
        if not md_path.exists():
            logger.error(
                f"Markdown converter produced no output for {html_path.name}; "
                "keeping original HTML."
            )
            return None

        # Delete original HTML file
        try:
            os.remove(html_path)
            logger.debug(f"Deleted original HTML file: {html_path}")
        except OSError as e:
            logger.warning(f"Failed to delete original HTML file {html_path}: {e}")

        return md_path
        
    except Exception as e:
        logger.error(f"Error converting HTML to MD for {html_path}: {e}")
        return None
