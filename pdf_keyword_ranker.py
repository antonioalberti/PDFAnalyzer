import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

from PyPDF2 import PdfReader

from keyword_search import KeywordSearcher


def extract_pdf_text(file_path: str) -> str:
    """Extract raw text from every page of a PDF file."""
    reader = PdfReader(file_path)
    text_chunks: List[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        text_chunks.append(f"Page {page_number}:\n{page_text}\n")
    return "\n".join(text_chunks)


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


def deduplicate_by_basename(paths: List[str]) -> List[str]:
    """Keep only the first occurrence of each filename (case-insensitive)."""
    seen: set[str] = set()
    unique_paths: List[str] = []
    for path in paths:
        name = os.path.basename(path).lower()
        if name in seen:
            continue
        seen.add(name)
        unique_paths.append(path)
    return unique_paths


def analyze_pdf(
    file_path: str,
    searcher: KeywordSearcher,
) -> Dict[str, int]:
    """Return a dict with counts of keyword occurrences per category for one PDF."""
    pdf_text = extract_pdf_text(file_path)
    occurrences = searcher.check_enabler_occurrences(pdf_text)
    return {category: len(matches) for category, matches in occurrences.items()}


def build_rankings(
    per_file_counts: Dict[str, Dict[str, int]],
    categories: List[str],
    top_n: int,
) -> Dict[str, List[Tuple[str, int]]]:
    rankings: Dict[str, List[Tuple[str, int]]] = {}
    for category in categories:
        sortable: List[Tuple[str, int]] = []
        for file_path, counts in per_file_counts.items():
            sortable.append((file_path, counts.get(category, 0)))
        # Sort descending by score, then alphabetically by filename to stabilize ordering
        sortable.sort(key=lambda item: (-item[1], os.path.basename(item[0]).lower()))
        # Filter out zero-score entries while keeping at most top_n
        filtered = [(file_path, score) for file_path, score in sortable if score > 0][:top_n]
        rankings[category] = filtered
    return rankings


def save_rankings(rankings: Dict[str, List[Tuple[str, int]]], output_path: str) -> None:
    """Persist rankings into a JSON file."""
    serializable = {
        category: [
            {"file": file_path, "score": score}
            for file_path, score in ranking
        ]
        for category, ranking in rankings.items()
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(serializable, fh, indent=2, ensure_ascii=False)


def print_rankings(rankings: Dict[str, List[Tuple[str, int]]]) -> None:
    for category, ranking in rankings.items():
        print(f"\n=== Top matches for category: {category} ===")
        if not ranking:
            print("No relevant PDFs found for this category.")
            continue
        for idx, (file_path, score) in enumerate(ranking, start=1):
            print(f"{idx:2d}. {os.path.basename(file_path)} -> {score} keyword hits")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank PDF files by keyword adherence per category."
    )
    parser.add_argument(
        "folder",
        help="Path to the folder containing PDF files to analyze.",
    )
    parser.add_argument(
        "--keywords",
        default="AIforcoding.json",
        help="Path to the JSON file containing categories and keywords (default: AIforcoding.json).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Number of top files to display per category (default: 10).",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Do not recursively scan subdirectories (recursive is enabled by default).",
    )
    parser.set_defaults(recursive=True)
    parser.add_argument(
        "--output",
        help="Optional path to save rankings as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.folder):
        print(f"Error: folder '{args.folder}' does not exist or is not a directory.")
        sys.exit(1)

    if not os.path.isfile(args.keywords):
        print(f"Error: keywords file '{args.keywords}' not found.")
        sys.exit(1)

    with open(args.keywords, "r", encoding="utf-8") as fh:
        enabler_keywords = json.load(fh)

    pdf_files = iter_pdf_files(args.folder, args.recursive)
    if not pdf_files:
        print("No PDF files found to analyze.")
        sys.exit(0)

    unique_pdf_files = deduplicate_by_basename(pdf_files)
    if len(unique_pdf_files) != len(pdf_files):
        skipped = len(pdf_files) - len(unique_pdf_files)
        print(f"Skipped {skipped} duplicate filename(s).")
    pdf_files = unique_pdf_files

    print(f"Found {len(pdf_files)} unique PDF files. Starting analysis...")

    searcher = KeywordSearcher(enabler_keywords)
    per_file_counts: Dict[str, Dict[str, int]] = {}

    for idx, pdf_file in enumerate(pdf_files, start=1):
        try:
            counts = analyze_pdf(pdf_file, searcher)
            per_file_counts[pdf_file] = counts
            print(f"[{idx}/{len(pdf_files)}] Processed {os.path.basename(pdf_file)}")
        except Exception as exc:
            print(
                f"Warning: failed to analyze '{pdf_file}'. Skipping. Reason: {exc}",
                file=sys.stderr,
            )

    rankings = build_rankings(per_file_counts, list(enabler_keywords.keys()), args.top_n)
    print_rankings(rankings)

    if args.output:
        save_rankings(rankings, args.output)
        print(f"\nRankings saved to {args.output}")


if __name__ == "__main__":
    main()
