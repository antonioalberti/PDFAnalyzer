"""generate_cost_summary.py
Post-processing script that reads all ``*_cost.txt`` files (including 2_ prefix)
and generates consolidated LaTeX tables for both Method 1 and Method 2.

Output files:
- 3_consolidated_costs.tex
- 3_consolidated_tokens.tex

Usage:
    python generate_cost_summary.py <source_folder>
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


def _wrap_table(tabular_lines: List[str], caption: str, label: str) -> List[str]:
    """Wrap tabular content in a full table environment."""
    return [
        r"\begin{table}[h]",
        r"    \centering",
        f"    \\caption{{{caption}}}",
        f"    \\label{{{label}}}",
    ] + ["    " + line for line in tabular_lines] + [
        r"\end{table}",
        "",
    ]


# ---------------------------------------------------------------------------
# Consolidated Table Builders
# ---------------------------------------------------------------------------

def build_consolidated_token_table(
    method1_data: Dict[str, Dict],
    method2_data: Dict[str, Dict],
    output_path: Path,
) -> None:
    """Build a LaTeX table showing token usage for both methods."""
    tabular: List[str] = [
        r"\begin{tabular}{lrrrr}",
        r"    \hline",
        r"    PDF Document & Prompt & Completion & Total & Calls \\",
        r"    \hline",
        r"    \multicolumn{5}{c}{\textbf{Method 1: Snippet-based Analysis}} \\",
        r"    \hline",
    ]

    m1_total = {"p": 0, "c": 0, "t": 0, "calls": 0}
    for i, stem in enumerate(sorted(method1_data.keys()), start=1):
        d = method1_data[stem]
        m1_total["p"] += d["prompt_tokens"]
        m1_total["c"] += d["completion_tokens"]
        m1_total["t"] += d["total_tokens"]
        m1_total["calls"] += d["calls"]
        safe = stem.replace("_", r"\_")
        tabular.append(f"    \\textbf{{F{i}:}} \\texttt{{{safe}}} & {d['prompt_tokens']:,} & {d['completion_tokens']:,} & {d['total_tokens']:,} & {d['calls']:,} \\\\")

    tabular.append(r"    \hline")
    tabular.append(f"    \textbf{{M1 Total}} & {m1_total['p']:,} & {m1_total['c']:,} & {m1_total['t']:,} & {m1_total['calls']:,} \\\\")
    tabular.append(r"    \hline")
    tabular.append(r"    \multicolumn{5}{c}{\textbf{Method 2: Full Text Analysis}} \\")
    tabular.append(r"    \hline")

    m2_total = {"p": 0, "c": 0, "t": 0, "calls": 0}
    for stem in sorted(method2_data.keys()):
        d = method2_data[stem]
        m2_total["p"] += d["prompt_tokens"]
        m2_total["c"] += d["completion_tokens"]
        m2_total["t"] += d["total_tokens"]
        m2_total["calls"] += d["calls"]
        safe = stem.replace("_", r"\_").replace("2\\_full\\_text\\_analysis", "Full Text Analysis")
        tabular.append(f"    \\texttt{{{safe}}} & {d['prompt_tokens']:,} & {d['completion_tokens']:,} & {d['total_tokens']:,} & {d['calls']:,} \\\\")

    tabular.append(r"    \hline")
    tabular.append(f"    \textbf{{M2 Total}} & {m2_total['p']:,} & {m2_total['c']:,} & {m2_total['t']:,} & {m2_total['calls']:,} \\\\")
    tabular.append(r"    \hline")
    
    grand_total_tokens = m1_total["t"] + m2_total["t"]
    grand_total_calls = m1_total["calls"] + m2_total["calls"]
    tabular.append(f"    \\textbf{{GRAND TOTAL}} & \\multicolumn{{2}}{{r}}{{}} & {grand_total_tokens:,} & {grand_total_calls:,} \\\\")
    tabular.append(r"    \hline")
    tabular.append(r"\end{tabular}")

    lines = _wrap_table(tabular, "Consolidated Token Usage (Method 1 vs Method 2)", "tab:consolidated-tokens")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved consolidated tokens: {output_path}")


def build_consolidated_cost_table(
    method1_data: Dict[str, Dict],
    method2_data: Dict[str, Dict],
    output_path: Path,
) -> None:
    """Build a LaTeX table showing costs for both methods."""
    tabular: List[str] = [
        r"\begin{tabular}{lrr}",
        r"    \hline",
        r"    PDF Document & API Calls & Cost (USD) \\",
        r"    \hline",
        r"    \multicolumn{3}{c}{\textbf{Method 1: Snippet-based Analysis}} \\",
        r"    \hline",
    ]

    m1_calls = 0
    m1_cost = 0.0
    for i, stem in enumerate(sorted(method1_data.keys()), start=1):
        d = method1_data[stem]
        m1_calls += d["calls"]
        m1_cost += d["cost_usd"]
        safe = stem.replace("_", r"\_")
        tabular.append(f"    \\textbf{{F{i}:}} \\texttt{{{safe}}} & {d['calls']:,} & ${d['cost_usd']:.6f} \\\\")

    tabular.append(r"    \hline")
    tabular.append(f"    \textbf{{M1 Total}} & {m1_calls:,} & ${m1_cost:.6f} \\\\")
    tabular.append(r"    \hline")
    tabular.append(r"    \multicolumn{3}{c}{\textbf{Method 2: Full Text Analysis}} \\")
    tabular.append(r"    \hline")

    m2_calls = 0
    m2_cost = 0.0
    for stem in sorted(method2_data.keys()):
        d = method2_data[stem]
        m2_calls += d["calls"]
        m2_cost += d["cost_usd"]
        safe = stem.replace("_", r"\_").replace("2\\_full\\_text\\_analysis", "Full Text Analysis")
        tabular.append(f"    \\texttt{{{safe}}} & {d['calls']:,} & ${d['cost_usd']:.6f} \\\\")

    tabular.append(r"    \hline")
    tabular.append(f"    \textbf{{M2 Total}} & {m2_calls:,} & ${m2_cost:.6f} \\\\")
    tabular.append(r"    \hline")
    
    grand_calls = m1_calls + m2_calls
    grand_cost = m1_cost + m2_cost
    tabular.append(f"    \textbf{{GRAND TOTAL}} & {grand_calls:,} & ${grand_cost:.6f} \\\\")
    tabular.append(r"    \hline")
    tabular.append(r"\end{tabular}")

    lines = _wrap_table(tabular, "Consolidated API Costs (Method 1 vs Method 2)", "tab:consolidated-costs")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(Fore.GREEN + f"Saved consolidated costs: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_folder")
    args = parser.parse_args()
    source_folder = Path(args.source_folder)

    if not source_folder.is_dir():
        sys.exit(1)

    # Method 1: Files like NIST.AI.100-1_cost.txt
    # Method 2: Files like 2_full_text_analysis_cost.txt
    all_cost_files = list(source_folder.glob("*_cost.txt"))
    
    method1_data = {}
    method2_data = {}

    for f in all_cost_files:
        if f.name.startswith("2_"):
            method2_data[f.stem.replace("_cost", "")] = parse_cost_file(f)
        elif f.name == "full_text_analysis_cost.txt":
            # Legacy name for method 2, treat as method 2
            method2_data["2_full_text_analysis"] = parse_cost_file(f)
        else:
            method1_data[f.stem.replace("_cost", "")] = parse_cost_file(f)

    build_consolidated_token_table(method1_data, method2_data, source_folder / "3_consolidated_tokens.tex")
    build_consolidated_cost_table(method1_data, method2_data, source_folder / "3_consolidated_costs.tex")


if __name__ == "__main__":
    main()