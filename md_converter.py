import os
import logging
from pathlib import Path
from bs4 import BeautifulSoup
import markdownify

logger = logging.getLogger(__name__)

def convert_html_to_md(html_path: Path | str) -> Path | None:
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
            
        md_path = html_path.with_suffix('.md')
        
        # Enforce UTF-8 encoding for reading
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # Parse HTML
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Convert to Markdown
        md_content = markdownify.markdownify(str(soup), heading_style="ATX")
        
        # Enforce UTF-8 encoding for writing
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
            
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
