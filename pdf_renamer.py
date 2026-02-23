import argparse
import html
import os
import re
import shutil
import sys
from typing import List

from PyPDF2 import PdfReader

# Try to import pdfplumber for content extraction
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


def iter_pdf_files(folder: str, recursive: bool) -> List[str]:
    """Return a sorted list of PDF file paths inside the folder."""
    pdf_paths: List[str] = []
    if recursive:
        for root, _, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(".pdf"):
                    pdf_paths.append(os.path.join(root, name))
    else:
        for name in os.listdir(folder):
            if name.lower().endswith(".pdf"):
                pdf_paths.append(os.path.join(folder, name))
    pdf_paths.sort()
    return pdf_paths


def extract_pdf_title_from_content(file_path: str) -> str | None:
    """Extract the title from the first page of the PDF content.
    
    Looks for the largest text that appears to be a title (common patterns
    in academic papers, articles, etc.)
    """
    if not PDFPLUMBER_AVAILABLE:
        return None
    
    try:
        with pdfplumber.open(file_path) as pdf:
            if len(pdf.pages) == 0:
                return None
            
            first_page = pdf.pages[0]
            text = first_page.extract_text()
            if not text:
                return None
            
            lines = text.split('\n')
            # Filter out empty lines and very short lines (likely not titles)
            candidates = [line.strip() for line in lines if len(line.strip()) > 10]
            
            if not candidates:
                return None
            
            # Patterns that indicate a line is NOT a title
            # Email addresses
            email_pattern = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
            # URL patterns
            url_pattern = re.compile(r'https?://|www\.')
            # Common non-title prefixes
            non_title_prefixes = ['abstract', 'introduction', 'keywords', 'doi:', 'http', 'university', 'department', 'college', 'school', 'author', 'date', 'volume', 'issue', 'page', 'received', 'accepted', 'published', 'copyright', 'journal', 'conference', 'proceedings', 'issn', 'isbn', 'thanks', 'acknowledgment']
            # Patterns that look like affiliations (usually contain commas and parenthetical info)
            affiliation_patterns = [',', 'department of', 'institute of', 'laboratory', 'lab ', ' center', 'centre for']
            
            best_title = None
            best_score = 0
            
            for line in candidates:
                line_lower = line.lower()
                
                # Skip lines with email addresses
                if email_pattern.search(line):
                    continue
                    
                # Skip lines with URLs
                if url_pattern.search(line_lower):
                    continue
                
                # Skip lines that start with common non-title prefixes
                if any(line_lower.startswith(prefix) for prefix in non_title_prefixes):
                    continue
                
                # Skip lines that look like affiliations (contain department/university info)
                if any(pattern in line_lower for pattern in affiliation_patterns):
                    # But allow if it looks more like a title (has more words, less parenthetical content)
                    if '(' in line and ')' in line:
                        # Has parenthetical content - likely affiliation
                        continue
                
                # Skip lines that are mostly numbers or very short in content
                words = line.split()
                if len(words) < 3:
                    continue
                
                # Check if line has mixed case (typical of titles)
                # Count uppercase words vs total words
                upper_words = sum(1 for w in words if w.isupper() and len(w) > 1)
                if upper_words > len(words) * 0.5 and not line[0].isupper():
                    # Too many uppercase words but doesn't start with capital
                    continue
                
                # Score based on length - prefer lines that look like titles
                # (not too long, not too short, have proper case)
                score = len(line)
                
                # Bonus for having proper title case (capitalized words)
                title_case_words = sum(1 for w in words if w and w[0].isupper())
                if title_case_words > len(words) * 0.7:
                    score *= 1.2
                
                # Penalize lines that are all uppercase
                if line.isupper():
                    score *= 0.5
                
                # Penalize very long lines (likely not titles)
                if len(line) > 200:
                    score *= 0.7
                
                if score > best_score:
                    best_score = score
                    best_title = line
            
            if best_title and best_score > 20:  # Minimum threshold
                return normalize_title(best_title)
                
    except Exception as e:
        print(f"Could not extract title from content for {file_path}: {e}", file=sys.stderr)
    
    return None


def extract_pdf_title(file_path: str) -> str | None:
    """Extract the title from PDF metadata or content."""
    # First try to get title from metadata
    try:
        reader = PdfReader(file_path)
        meta = reader.metadata
        if meta and meta.title:
            title = normalize_title(meta.title)
            # Check if the title is meaningful (not just garbage)
            if title and len(title) > 3 and not title.startswith('/'):
                return title
    except Exception as e:
        print(f"Could not read metadata from {file_path}: {e}", file=sys.stderr)
    
    # If metadata doesn't have a good title, try to extract from content
    title_from_content = extract_pdf_title_from_content(file_path)
    if title_from_content:
        print(f"No metadata title for '{os.path.basename(file_path)}'; extracted title from content.")
        return title_from_content
    
    return None


def normalize_title(value: str) -> str:
    """Normalize whitespace and decode HTML entities."""
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def derive_title_from_filename(filename: str) -> str | None:
    """Use the existing filename to build a readable title."""
    base = os.path.splitext(filename)[0]
    if not base:
        return None

    base = base.replace("_", " ")
    base = base.replace(".", " ")
    base = re.sub(r"\s+", " ", base)
    base = base.strip()
    if not base:
        return None

    return normalize_title(base)


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be a valid Windows filename."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    max_len = 240
    if len(name) > max_len:
        name = name[:max_len]
        name = name.rsplit(" ", 1)[0]
    name = name.strip()
    return name.strip('.')


def rename_pdf_with_title(file_path: str, dry_run: bool = False) -> None:
    """Rename a single PDF file based on its title."""
    directory = os.path.dirname(file_path)
    old_filename = os.path.basename(file_path)

    title = extract_pdf_title(file_path)
    fallback_used = False

    if not title:
        fallback = derive_title_from_filename(old_filename)
        if fallback:
            title = fallback
            fallback_used = True
            print(f"No metadata title for '{old_filename}'; deriving title from filename.")
        else:
            print(f"Could not determine title for '{old_filename}'. Skipping.")
            return

    new_filename_base = sanitize_filename(title)
    if not new_filename_base:
        print(f"Sanitized title for '{old_filename}' is empty. Skipping.")
        return

    new_filename = f"{new_filename_base}.pdf"

    if old_filename.lower() == new_filename.lower():
        note = "already named correctly"
        note = "already named correctly" if not fallback_used else "needs no change after fallback"
        print(f"'{old_filename}' is {note}. Skipping.")
        return

    new_filepath = os.path.join(directory, new_filename)
    
    # If the target file already exists and is different from the source, we need to handle it
    if os.path.exists(new_filepath) and os.path.abspath(new_filepath) != os.path.abspath(file_path):
        # Remove the existing file first, then we can move the source file
        print(f"Target file '{new_filename}' already exists. Removing old file and overwriting.")
        try:
            os.remove(new_filepath)
        except OSError as e:
            print(f"Error removing existing file '{new_filename}': {e}", file=sys.stderr)
            return
    elif os.path.exists(new_filepath) and os.path.abspath(new_filepath) == os.path.abspath(file_path):
        # Same file (e.g., case difference on case-insensitive filesystem)
        print(f"'{old_filename}' is already named correctly. Skipping.")
        return

    print(f"Renaming '{old_filename}' -> '{new_filename}'")
    if not dry_run:
        try:
            shutil.move(file_path, new_filepath)
        except OSError as e:
            print(f"Error renaming '{old_filename}': {e}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Rename PDF files based on their titles."
    )
    parser.add_argument(
        "folder",
        help="Path to the folder containing PDF files to rename.",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Do not recursively scan subdirectories (recursive is enabled by default).",
    )
    parser.set_defaults(recursive=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be renamed without actually renaming files.",
    )
    return parser.parse_args()


def main() -> None:
    """Main function."""
    args = parse_args()

    if not os.path.isdir(args.folder):
        print(f"Error: folder '{args.folder}' does not exist or is not a directory.")
        sys.exit(1)

    pdf_files = iter_pdf_files(args.folder, args.recursive)
    if not pdf_files:
        print("No PDF files found to rename.")
        sys.exit(0)

    print(f"Found {len(pdf_files)} PDF files. Starting renaming process...")

    for pdf_file in pdf_files:
        rename_pdf_with_title(pdf_file, args.dry_run)

    print("\nRenaming process finished.")


if __name__ == "__main__":
    main()
