#!/usr/bin/env python3
"""
Script to replace all instances of pl.String with pl.String in Python files.
"""

import os
import re
from pathlib import Path

def replace_utf8_with_string():
    """Replace pl.String with pl.String in all Python files."""
    
    # Find all Python files
    python_files = []
    for root, dirs, files in os.walk('.'):
        # Skip certain directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]
        
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    
    replacements_made = 0
    
    for file_path in python_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Replace pl.String with pl.String
            # Use word boundaries to avoid false matches
            original_content = content
            content = re.sub(r'\bpl\.Utf8\b', 'pl.String', content)
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"✅ Updated {file_path}")
                replacements_made += 1
                
        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")
    
    print(f"\n🎯 Replaced pl.String with pl.String in {replacements_made} files")

if __name__ == "__main__":
    replace_utf8_with_string()