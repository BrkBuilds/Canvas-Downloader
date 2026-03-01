import os
from pathlib import Path

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

def convert_code_to_txt(file_path: str | Path) -> str | None:
    """
    Converts a code/data file to a .txt file by renaming the extension to _ext.txt
    and prepending a header. It explicitly writes in UTF-8 and deletes the original file.
    
    Returns the absolute path of the new .txt file as a string if successful, else None.
    """
    original_path = Path(file_path)
    
    # Check if the suffix is in our supported list
    if original_path.suffix.lower() not in CODE_EXTENSIONS:
        return None
        
    # Construct new name: filename.py -> filename_py.txt
    clean_suffix = original_path.suffix.replace('.', '_')
    new_name = f"{original_path.stem}{clean_suffix}.txt"
    txt_path = original_path.with_name(new_name)
    
    try:
        # Read the original file safely, replacing bad characters
        with open(original_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            
        # Add a small header so NotebookLM knows what this is
        header = f"--- Original File: {original_path.name} ---\n\n"
        
        # Write to the new .txt file forcing UTF-8 encoding
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(header + content)
            
        # Delete the original code file
        original_path.unlink()
        
        return str(txt_path)
    except Exception as e:
        print(f"Failed to convert code file {original_path.name}: {e}")
        return None
