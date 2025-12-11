import argparse
import html
import os
import re
import sys
from typing import List

from PyPDF2 import PdfReader


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


def extract_pdf_title(file_path: str) -> str | None:
    """Extract the title from PDF metadata."""
    try:
        reader = PdfReader(file_path)
        meta = reader.metadata
        if meta and meta.title:
            return normalize_title(meta.title)
    except Exception as e:
        print(f"Could not read metadata from {file_path}: {e}", file=sys.stderr)
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
    counter = 1
    while os.path.exists(new_filepath):
        new_filename = f"{new_filename_base} ({counter}).pdf"
        new_filepath = os.path.join(directory, new_filename)
        counter += 1

    print(f"Renaming '{old_filename}' -> '{new_filename}'")
    if not dry_run:
        try:
            os.rename(file_path, new_filepath)
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
