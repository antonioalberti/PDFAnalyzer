"""generate_occurrences.py
Post-processing script that generates ``*_occurrences.txt`` files for PDFs
that have already been analysed by main.py.

It reads the ``*_significant_paragraphs_category_N.txt`` files produced
during analysis, re-runs the (free) keyword search on the extracted PDF
text, and writes the occurrences summary — no LLM calls are made.

New features:
- Per-category percentages (significant / found * 100)
- LaTeX table row per PDF embedded in each occurrences file
- Final ``summary_table.tex`` with all PDFs combined

Usage:
    python generate_occurrences.py <source_folder> <keywords_json> [--start N] [--end N]

Example:
    python generate_occurrences.py /path/to/Standards cloud.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from colorama import Fore, Style, init

init(autoreset=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_keywords(keywords_path: Path) -> Dict[str, List[str]]:
    with keywords_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {str(k): [str(w) for w in v] for k, v in data.items()}


def count_raw_occurrences(pdf_text: str, keywords: List[str]) -> int:
    """Count how many times ANY keyword from the list appears in the text (case-insensitive)."""
    text_lower = pdf_text.lower()
    total = 0
    for kw in keywords:
        start = 0
        kw_lower = kw.lower()
        while True:
            pos = text_lower.find(kw_lower, start)
            if pos == -1:
                break
            total += 1
            start = pos + 1
    return total


def count_keyword_in_paragraphs(paragraphs: List[str], keywords: List[str]) -> Counter:
    """For each significant paragraph, count how many times each keyword appears."""
    counter: Counter = Counter()
    for para in paragraphs:
        para_lower = para.lower()
        for kw in keywords:
            kw_lower = kw.lower()
            start = 0
            while True:
                pos = para_lower.find(kw_lower, start)
                if pos == -1:
                    break
                counter[kw] += 1
                start = pos + 1
    return counter


def read_significant_paragraphs(sig_file: Path) -> List[str]:
    """Read significant paragraphs from file (separated by blank lines)."""
    if not sig_file.exists():
        return []
    text = sig_file.read_text(encoding="utf-8", errors="replace")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return paragraphs


def pct(found: int, significant: int) -> str:
    """Return a percentage string, handling division by zero."""
    if found == 0:
        return "0.0"
    return f"{(significant / found) * 100:.1f}"


def _wrap_table(tabular_lines: List[str], caption: str, label: str) -> List[str]:
    """Wrap tabular content in a full table environment."""
    return [
        r"\begin{table}[h]",
        r"    \centering",
    ] + ["    " + line for line in tabular_lines] + [
        f"    \\caption{{{caption}}}",
        f"    \\label{{{label}}}",
        r"\end{table}",
        "",
    ]


def _cat_comments(category_names: List[str]) -> List[str]:
    """Return category legend comments for LaTeX tables."""
    return [f"% C{i+1}: {name}" for i, name in enumerate(category_names)]


# ---------------------------------------------------------------------------
# Per-PDF file generation
# ---------------------------------------------------------------------------

def generate_occurrences_file(
    pdf_path: Path,
    enabler_keywords: Dict[str, List[str]],
    pdf_text: str,
) -> Tuple[List[int], List[int], List[Counter]]:
    """Generate the *_occurrences.txt file for one PDF.

    Returns:
        - raw_counts: list of int, one per category
        - sig_counts: list of int, one per category
        - kw_counters: list of Counter, one per category (keyword counts in significant paragraphs)
    """

    sep = "=" * 70
    thin = "-" * 70
    lines: List[str] = [
        sep,
        f"OCCURRENCES SUMMARY: {pdf_path.name}",
        sep,
        "",
        "CATEGORY OVERVIEW",
        thin,
    ]

    total_found = 0
    total_significant = 0
    raw_counts: List[int] = []
    sig_counts: List[int] = []
    kw_counters: List[Counter] = []

    for cat_idx, (enabler, keywords) in enumerate(enabler_keywords.items(), start=1):
        # Raw occurrences (keyword search, no LLM)
        found = count_raw_occurrences(pdf_text, keywords)

        # Significant occurrences — read from the file produced by main.py
        sig_file = pdf_path.parent / f"{pdf_path.stem}_significant_paragraphs_category_{cat_idx}.txt"
        sig_paragraphs = read_significant_paragraphs(sig_file)
        significant = len(sig_paragraphs)

        raw_counts.append(found)
        sig_counts.append(significant)
        total_found += found
        total_significant += significant

        percentage = pct(found, significant)

        lines.append(f"Category {cat_idx}: {enabler}")
        lines.append(f"  Occurrences found (before LLM filter):  {found:>5}")
        lines.append(f"  Significant occurrences (after filter):  {significant:>5}")
        lines.append(f"  Relevance rate:                           {percentage:>5}%")

        kw_counter: Counter = Counter()
        if sig_paragraphs:
            kw_counter = count_keyword_in_paragraphs(sig_paragraphs, keywords)
            if kw_counter:
                lines.append("  Keyword counts in significant paragraphs:")
                for kw, count in sorted(kw_counter.items(), key=lambda x: (-x[1], x[0])):
                    lines.append(f"    {kw}: {count}")
            else:
                lines.append(f"  Keywords searched: {', '.join(keywords)}")
        else:
            lines.append(f"  Keywords searched: {', '.join(keywords)}")
            lines.append("  No significant occurrences.")
        lines.append("")

        kw_counters.append(kw_counter)

    total_pct = pct(total_found, total_significant)

    lines += [
        thin,
        "TOTALS",
        f"  Total occurrences found (before LLM filter):  {total_found:>5}",
        f"  Total significant occurrences (after filter): {total_significant:>5}",
        f"  Overall relevance rate:                       {total_pct:>5}%",
        sep,
        "",
        "LATEX TABLE ROW",
        thin,
    ]

    # Build LaTeX row for this PDF (no spaces around /)
    short_name = pdf_path.stem.replace("_", r"\_")
    cells = " & ".join(
        f"{found}/{sig} ({pct(found,sig)}\\%)"
        for found, sig in zip(raw_counts, sig_counts)
    )
    latex_row = f"\\texttt{{{short_name}}} & {cells} & {total_found}/{total_significant} ({total_pct}\\%) \\"  # noqa: E501
    lines.append(latex_row)
    lines.append(sep)

    output_path = pdf_path.parent / f"{pdf_path.stem}_occurrences.txt"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved: {output_path}" + Style.RESET_ALL)

    return raw_counts, sig_counts, kw_counters


# ---------------------------------------------------------------------------
# Combined LaTeX tables
# ---------------------------------------------------------------------------

def build_counts_table(
    pdf_names: List[str],
    all_raw: List[List[int]],
    all_sig: List[List[int]],
    category_names: List[str],
    output_path: Path,
) -> None:
    """Write a LaTeX table showing raw/significant counts per PDF."""

    n_cats = len(all_raw[0]) if all_raw else 0
    cols = "l" + "c" * n_cats + "c"

    tabular: List[str] = [
        r"\begin{tabular}{" + cols + r"}",
        r"    \hline",
    ]

    cat_headers = [f"C{i+1}" for i in range(n_cats)]
    header = "PDF Document & " + " & ".join(cat_headers) + r" & Total \\"
    tabular.append("    " + header)
    tabular.append(r"    \hline")

    for name, raw_row, sig_row in zip(pdf_names, all_raw, all_sig):
        short_name = name.replace("_", r"\_")
        cells = " & ".join(f"{found}/{sig}" for found, sig in zip(raw_row, sig_row))
        total_found = sum(raw_row)
        total_sig = sum(sig_row)
        row = f"\\texttt{{{short_name}}} & {cells} & {total_found}/{total_sig} \\"  # noqa: E501
        tabular.append("    " + row)

    tabular.append(r"    \hline")
    tabular.append(r"\end{tabular}")

    lines = (
        _cat_comments(category_names)
        + [""]
        + _wrap_table(
            tabular,
            caption="Keyword occurrences found and significant per PDF and category.",
            label="tab:occurrence-counts",
        )
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved counts table: {output_path}" + Style.RESET_ALL)


def build_percentages_table(
    pdf_names: List[str],
    all_raw: List[List[int]],
    all_sig: List[List[int]],
    category_names: List[str],
    output_path: Path,
) -> None:
    """Write a LaTeX table showing relevance percentages per PDF."""

    n_cats = len(all_raw[0]) if all_raw else 0
    cols = "l" + "c" * n_cats + "c"

    tabular: List[str] = [
        r"\begin{tabular}{" + cols + r"}",
        r"    \hline",
    ]

    cat_headers = [f"C{i+1}" for i in range(n_cats)]
    header = "PDF Document & " + " & ".join(cat_headers) + r" & Total \\"
    tabular.append("    " + header)
    tabular.append(r"    \hline")

    for name, raw_row, sig_row in zip(pdf_names, all_raw, all_sig):
        short_name = name.replace("_", r"\_")
        cells = " & ".join(f"{pct(found, sig)}\\%" for found, sig in zip(raw_row, sig_row))
        total_found = sum(raw_row)
        total_sig = sum(sig_row)
        total_p = pct(total_found, total_sig)
        row = f"\\texttt{{{short_name}}} & {cells} & {total_p}\\% \\"  # noqa: E501
        tabular.append("    " + row)

    tabular.append(r"    \hline")
    tabular.append(r"\end{tabular}")

    lines = (
        _cat_comments(category_names)
        + [""]
        + _wrap_table(
            tabular,
            caption="Relevance rate of keyword occurrences per PDF and category.",
            label="tab:occurrence-percentages",
        )
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved percentages table: {output_path}" + Style.RESET_ALL)


def build_keyword_latex_table(
    pdf_names: List[str],
    all_kw_counters: List[List[Counter]],
    category_names: List[str],
    output_path: Path,
) -> None:
    """Write a LaTeX file with per-category keyword-count tables."""

    n_cats = len(category_names)
    n_pdfs = len(pdf_names)

    lines: List[str] = [
        "% LaTeX keyword-count tables generated by generate_occurrences.py",
        "% Each sub-table shows keyword occurrences in significant paragraphs.",
        "",
    ]

    for cat_idx, cat_name in enumerate(category_names):
        # Collect all keywords that appear in at least one PDF for this category
        all_keywords: set[str] = set()
        for pdf_idx in range(n_pdfs):
            all_keywords.update(all_kw_counters[pdf_idx][cat_idx].keys())
        sorted_keywords = sorted(all_keywords, key=lambda kw: kw.lower())

        if not sorted_keywords:
            lines.append(f"% Category {cat_idx + 1}: {cat_name} — no significant keyword occurrences.")
            lines.append("")
            continue

        cols = "l" + "r" * n_pdfs + "r"
        tabular: List[str] = [
            r"\begin{tabular}{" + cols + r"}",
            r"    \hline",
        ]

        # Header
        safe_names = [name.replace("_", r"\_") for name in pdf_names]
        header = "Keyword & " + " & ".join(f"\\texttt{{{n}}}" for n in safe_names) + r" & Total \\"  # noqa: E501
        tabular.append("    " + header)
        tabular.append(r"    \hline")

        # Data rows
        col_totals: List[int] = [0] * n_pdfs
        for kw in sorted_keywords:
            counts: List[int] = []
            row_total = 0
            for pdf_idx in range(n_pdfs):
                c = all_kw_counters[pdf_idx][cat_idx].get(kw, 0)
                counts.append(c)
                col_totals[pdf_idx] += c
                row_total += c
            safe_kw = kw.replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")
            cells = " & ".join(str(c) for c in counts)
            tabular.append(f"    {safe_kw} & {cells} & {row_total} \\\\")

        tabular.append(r"    \hline")
        total_cells = " & ".join(str(t) for t in col_totals)
        grand_total = sum(col_totals)
        tabular.append(f"    \\textbf{{Total}} & {total_cells} & {grand_total} \\\\")
        tabular.append(r"    \hline")
        tabular.append(r"\end{tabular}")

        lines += _wrap_table(
            tabular,
            caption=f"Keyword occurrences in significant paragraphs: {cat_name}.",
            label=f"tab:keywords-cat{cat_idx + 1}",
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved keyword LaTeX table: {output_path}" + Style.RESET_ALL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate *_occurrences.txt files from already-analysed PDFs (no LLM calls)."
    )
    parser.add_argument("source_folder", help="Folder containing the PDF files.")
    parser.add_argument("keywords_path", help="Path to the keywords JSON file.")
    parser.add_argument("--start", type=int, default=0, help="Start index (0-based, inclusive).")
    parser.add_argument("--end", type=int, default=None, help="End index (0-based, inclusive). Default: last file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    source_folder = Path(args.source_folder)
    keywords_path = Path(args.keywords_path)

    if not source_folder.is_dir():
        print(Fore.RED + f"Error: folder not found: {source_folder}" + Style.RESET_ALL)
        sys.exit(1)
    if not keywords_path.is_file():
        print(Fore.RED + f"Error: keywords file not found: {keywords_path}" + Style.RESET_ALL)
        sys.exit(1)

    enabler_keywords = load_keywords(keywords_path)
    print(Fore.CYAN + f"Loaded {len(enabler_keywords)} enabler categories from {keywords_path.name}" + Style.RESET_ALL)

    pdf_files = sorted(
        [p for p in source_folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
        key=lambda p: p.name.lower(),
    )

    if not pdf_files:
        print(Fore.YELLOW + "No PDF files found." + Style.RESET_ALL)
        sys.exit(0)

    end_idx = args.end if args.end is not None else len(pdf_files) - 1
    selected = pdf_files[args.start : end_idx + 1]

    print(Fore.CYAN + f"Processing {len(selected)} PDF(s):" + Style.RESET_ALL)
    for p in selected:
        print(f"  {p.name}")

    all_pdf_names: List[str] = []
    all_raw: List[List[int]] = []
    all_sig: List[List[int]] = []
    all_kw_counters: List[List[Counter]] = []

    for pdf_path in selected:
        print(Fore.BLUE + f"\n--- {pdf_path.name} ---" + Style.RESET_ALL)

        # Use extracted text file if available (faster than re-parsing PDF)
        txt_path = pdf_path.with_suffix(".txt")
        if txt_path.exists():
            pdf_text = txt_path.read_text(encoding="utf-8", errors="replace")
            print(Fore.CYAN + f"  Using extracted text from {txt_path.name}" + Style.RESET_ALL)
        else:
            print(Fore.YELLOW + f"  No .txt file found; trying PDF extraction..." + Style.RESET_ALL)
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(str(pdf_path))
                pdf_text = "".join(
                    (page.extract_text() or "") for page in reader.pages
                )
            except Exception as exc:
                print(Fore.RED + f"  Failed to extract text: {exc}" + Style.RESET_ALL)
                continue

        raw_counts, sig_counts, kw_counters = generate_occurrences_file(pdf_path, enabler_keywords, pdf_text)
        all_pdf_names.append(pdf_path.stem)
        all_raw.append(raw_counts)
        all_sig.append(sig_counts)
        all_kw_counters.append(kw_counters)

    # Build combined LaTeX tables
    if all_pdf_names:
        counts_path = source_folder / "summary_counts_table.tex"
        build_counts_table(all_pdf_names, all_raw, all_sig, list(enabler_keywords.keys()), counts_path)

        pct_path = source_folder / "summary_percentages_table.tex"
        build_percentages_table(all_pdf_names, all_raw, all_sig, list(enabler_keywords.keys()), pct_path)

        kw_latex_path = source_folder / "keyword_table.tex"
        build_keyword_latex_table(all_pdf_names, all_kw_counters, list(enabler_keywords.keys()), kw_latex_path)

    print(Fore.GREEN + "\nDone." + Style.RESET_ALL)


if __name__ == "__main__":
    main()
