import os
from pathlib import Path

def compile_urls_to_txt(course_dir: str | Path, course_name: str) -> Path | None:
    """
    Scans a course directory for .url files, extracts the links, and compiles them
    into a single NotebookLM_External_Links.txt file in the course root.
    """
    course_path = Path(course_dir)
    url_files = list(course_path.rglob("*.url"))
    
    if not url_files:
        return None
        
    compiled_links = []
    
    for url_file in url_files:
        try:
            with open(url_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                for line in lines:
                    if line.strip().upper().startswith("URL="):
                        link = line.strip()[4:]
                        # Append the name (without .url) and the link
                        compiled_links.append(f"📌 {url_file.stem}\n🔗 {link}\n")
                        break
        except Exception as e:
            print(f"Failed to read {url_file.name}: {e}")
            
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
