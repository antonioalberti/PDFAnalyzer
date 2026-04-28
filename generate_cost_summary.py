"""generate_cost_summary.py
Post-processing script that reads ``*_cost.txt`` files produced by main.py
and generates a per-PDF cost/tokens summary plus two LaTeX tables:
- Token usage table (prompt, completion, total)
- Cost table (total cost in USD)

Usage:
    python generate_cost_summary.py <source_folder> [--start N] [--end N]

Example:
    python generate_cost_summary.py /path/to/Standards
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from colorama import Fore, Style, init

init(autoreset=True)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_cost_file(cost_path: Path) -> Dict[str, float | int]:
    """Extract key metrics from a *_cost.txt file."""

    text = cost_path.read_text(encoding="utf-8", errors="replace")

    # Extract numbers using regex
    def find_int(label: str) -> int:
        pattern = rf"{label}:\s+([\d,]+)"
        m = re.search(pattern, text)
        return int(m.group(1).replace(",", "")) if m else 0

    def find_float(label: str) -> float:
        pattern = rf"{label}:\s+\$?([\d.]+)"
        m = re.search(pattern, text)
        return float(m.group(1)) if m else 0.0

    return {
        "prompt_tokens": find_int("Prompt tokens"),
        "completion_tokens": find_int("Completion tokens"),
        "total_tokens": find_int("Total tokens"),
        "calls": find_int("Total API calls"),
        "cost_usd": find_float("Total cost"),
    }


# ---------------------------------------------------------------------------
# Output generators
# ---------------------------------------------------------------------------

def write_text_summary(
    pdf_stems: List[str],
    data: Dict[str, Dict[str, float | int]],
    output_path: Path,
) -> None:
    """Write a plain-text summary of cost and tokens per PDF."""

    sep = "=" * 70
    thin = "-" * 70
    lines = [sep, "COST AND TOKEN SUMMARY FOR ALL PDFs", sep, ""]

    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    total_calls = 0
    total_cost = 0.0

    for stem in pdf_stems:
        d = data[stem]
        prompt = int(d["prompt_tokens"])
        completion = int(d["completion_tokens"])
        tokens = int(d["total_tokens"])
        calls = int(d["calls"])
        cost = float(d["cost_usd"])

        total_prompt += prompt
        total_completion += completion
        total_tokens += tokens
        total_calls += calls
        total_cost += cost

        lines.append(f"PDF: {stem}.pdf")
        lines.append(f"  API calls:         {calls:,}")
        lines.append(f"  Prompt tokens:     {prompt:,}")
        lines.append(f"  Completion tokens: {completion:,}")
        lines.append(f"  Total tokens:      {tokens:,}")
        lines.append(f"  Cost:              ${cost:.8f} USD")
        lines.append("")

    lines += [
        thin,
        "GRAND TOTALS",
        f"  Total API calls:         {total_calls:,}",
        f"  Total prompt tokens:     {total_prompt:,}",
        f"  Total completion tokens: {total_completion:,}",
        f"  Total tokens:            {total_tokens:,}",
        f"  Total cost:              ${total_cost:.8f} USD",
        sep,
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved text summary: {output_path}" + Style.RESET_ALL)


def build_token_latex_table(
    pdf_stems: List[str],
    data: Dict[str, Dict[str, float | int]],
    output_path: Path,
) -> None:
    """Build a LaTeX table showing token usage per PDF."""

    lines: List[str] = [
        r"% LaTeX table: TOKEN USAGE per PDF",
        r"% Paste inside a table environment.",
        r"% No extra packages required; uses standard \hline.",
        r"",
        r"\begin{tabular}{lrrrr}",
        r"\hline",
        r"PDF Document & Prompt & Completion & Total & Calls \\",
        r"\hline",
    ]

    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    total_calls = 0

    for stem in pdf_stems:
        d = data[stem]
        prompt = int(d["prompt_tokens"])
        completion = int(d["completion_tokens"])
        tokens = int(d["total_tokens"])
        calls = int(d["calls"])

        total_prompt += prompt
        total_completion += completion
        total_tokens += tokens
        total_calls += calls

        safe = stem.replace("_", r"\_")
        lines.append(
            f"\\texttt{{{safe}}} & {prompt:,} & {completion:,} & {tokens:,} & {calls:,} \\\\"
        )

    lines.append(r"\hline")
    safe_total = "TOTAL"
    lines.append(
        f"\\textbf{{{safe_total}}} & {total_prompt:,} & {total_completion:,} & {total_tokens:,} & {total_calls:,} \\\\"
    )
    lines.append(r"\hline")
    lines.append(r"\end{tabular}")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved token LaTeX table: {output_path}" + Style.RESET_ALL)


def build_cost_latex_table(
    pdf_stems: List[str],
    data: Dict[str, Dict[str, float | int]],
    output_path: Path,
) -> None:
    """Build a LaTeX table showing cost per PDF."""

    lines: List[str] = [
        r"% LaTeX table: COST per PDF",
        r"% Paste inside a table environment.",
        r"% No extra packages required; uses standard \hline.",
        r"",
        r"\begin{tabular}{lrr}",
        r"\hline",
        r"PDF Document & API Calls & Cost (USD) \\",
        r"\hline",
    ]

    total_calls = 0
    total_cost = 0.0

    for stem in pdf_stems:
        d = data[stem]
        calls = int(d["calls"])
        cost = float(d["cost_usd"])

        total_calls += calls
        total_cost += cost

        safe = stem.replace("_", r"\_")
        lines.append(f"\\texttt{{{safe}}} & {calls:,} & ${cost:.6f}$ \\\\")

    lines.append(r"\hline")
    lines.append(
        f"\\textbf{{TOTAL}} & {total_calls:,} & ${total_cost:.6f}$ \\\\"
    )
    lines.append(r"\hline")
    lines.append(r"\end{tabular}")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved cost LaTeX table: {output_path}" + Style.RESET_ALL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate cost/token summaries and LaTeX tables from *_cost.txt files."
    )
    parser.add_argument("source_folder", help="Folder containing *_cost.txt files.")
    parser.add_argument("--start", type=int, default=0, help="Start index (0-based, inclusive).")
    parser.add_argument("--end", type=int, default=None, help="End index (0-based, inclusive). Default: last file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_folder = Path(args.source_folder)

    if not source_folder.is_dir():
        print(Fore.RED + f"Error: folder not found: {source_folder}" + Style.RESET_ALL)
        sys.exit(1)

    # Find all cost files and sort
    cost_files = sorted(
        [p for p in source_folder.iterdir() if p.is_file() and p.name.endswith("_cost.txt")],
        key=lambda p: p.name.lower(),
    )

    if not cost_files:
        print(Fore.YELLOW + "No *_cost.txt files found." + Style.RESET_ALL)
        sys.exit(0)

    end_idx = args.end if args.end is not None else len(cost_files) - 1
    selected = cost_files[args.start : end_idx + 1]

    print(Fore.CYAN + f"Processing {len(selected)} cost file(s):" + Style.RESET_ALL)
    for f in selected:
        print(f"  {f.name}")

    data: Dict[str, Dict[str, float | int]] = {}
    pdf_stems: List[str] = []

    for cost_file in selected:
        stem = cost_file.stem.replace("_cost", "")
        pdf_stems.append(stem)
        data[stem] = parse_cost_file(cost_file)
        print(Fore.CYAN + f"  {stem}: {data[stem]['calls']} calls, ${data[stem]['cost_usd']:.6f}" + Style.RESET_ALL)

    # Write outputs
    write_text_summary(pdf_stems, data, source_folder / "cost_summary.txt")
    build_token_latex_table(pdf_stems, data, source_folder / "token_table.tex")
    build_cost_latex_table(pdf_stems, data, source_folder / "cost_table.tex")

    print(Fore.GREEN + "\nDone." + Style.RESET_ALL)


if __name__ == "__main__":
    main()