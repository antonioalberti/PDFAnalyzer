import os
import re
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from colorama import Fore, Style, init
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from llm_query import LLMAnalyzer

# Initialize colorama
init(autoreset=True)

class FullPDFAnalyzer:
    def __init__(self, source_folder: str, keywords_path: str, output_folder: str):
        self.source_folder = Path(source_folder)
        self.keywords_path = Path(keywords_path)
        self.output_folder = Path(output_folder)
        self.model_name = "google/gemini-2.5-pro"
        self.llm_analyzer = LLMAnalyzer()
        self.categories = self._load_categories()
        
    def _load_categories(self) -> Dict[str, List[str]]:
        with open(self.keywords_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def extract_text(self, pdf_path: Path) -> str:
        print(Fore.CYAN + f"Extracting text from {pdf_path.name}..." + Style.RESET_ALL)
        reader = PdfReader(str(pdf_path))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text

    def analyze_category(self, pdf_text: str, category: str, keywords: List[str]) -> Tuple[str, int]:
        prompt = f"""You are an expert assistant analyzing a scientific paper for coverage of technological criteria.

CONTEXT:
You are going to analyse the enabler/category: {category}
Associated keywords: {', '.join(keywords)}

FULL PAPER TEXT:
{pdf_text}

TASK:
Considering the paper text above, write no more than ONE SINGLE PARAGRAPH summarizing how well the paper covers the category '{category}' based on the provided keywords and the general content.

Considering all above and the current state of the art in the article area, give a note for this paper after the single PARAGRAPH in a new line. The format must be: NOTE: X, where X is the result of your evaluation between 0 and 10. Answer in English."""

        print(Fore.YELLOW + f"  Analyzing category: {category}..." + Style.RESET_ALL)
        response = self.llm_analyzer.analyze({}, prompt, model_name=self.model_name)
        
        # Extract note
        note = 0
        for line in response.split('\n'):
            if 'NOTE:' in line:
                try:
                    note_str = line.split('NOTE:')[1].strip()
                    # Handle cases like "8/10" or "8.5"
                    note = float(note_str.split('/')[0])
                except:
                    note = 0
        
        return response, note

    def generate_latex_tables(self, results: Dict[str, Dict[str, float]]):
        # results format: {pdf_name: {category: note}}
        pdf_names = sorted(results.keys())
        cat_names = list(self.categories.keys())
        
        # Summary Counts Table (using notes as a proxy for "significance" in this full-text version)
        # Since we don't have keyword counts in this version, we'll just show the notes
        latex_counts = [
            "\\begin{table*}[h]",
            "    \\centering",
            "    \\caption{Evaluation scores assigned by LLM (Full Text Analysis - Method 2) per PDF and category.}",
            "    \\label{tab:full-text-notes}",
            "    \\begin{tabular}{l" + "c" * len(cat_names) + "c}",
            "        \\hline",
            "        PDF Document & " + " & ".join([f"C{i+1}" for i in range(len(cat_names))]) + " & Total \\\\",
            "        \\hline"
        ]
        
        for i, pdf in enumerate(pdf_names, start=1):
            safe_pdf = pdf.replace("_", r"\_")
            row = [f"\\textbf{{F{i}:}} \\texttt{{{safe_pdf}}}"]
            total_note = 0
            for cat in cat_names:
                note = results[pdf].get(cat, 0)
                row.append(f"{note:.1f}")
                total_note += note
            row.append(f"{total_note:.1f}")
            latex_counts.append("        " + " & ".join(row) + " \\\\")
            
        latex_counts.extend([
            "        \\hline",
            "    \\end{tabular}",
            "\\end{table*}"
        ])
        
        output_path = self.output_folder / "2_alternative_summary_notes_table.tex"
        output_path.write_text("\n".join(latex_counts), encoding="utf-8")
        print(Fore.GREEN + f"Saved LaTeX table to {output_path}" + Style.RESET_ALL)

    def generate_cost_table(self):
        summary = self.llm_analyzer.get_usage_summary()
        
        # Find all *_cost.txt files to ensure we have all PDFs
        cost_files = sorted(list(self.output_folder.glob("*_cost.txt")))
        
        rows = []
        total_calls = summary['calls']
        total_cost = summary['total_cost_usd']
        
        # Add the full text analysis row first
        rows.append(f"        \\texttt{{Full Text Analysis}} & {summary['calls']} & ${summary['total_cost_usd']:.6f} \\\\")
        
        pdf_idx = 1
        for cost_file in cost_files:
            if cost_file.name == "full_text_analysis_cost.txt":
                continue
            
            stem = cost_file.stem.replace("_cost", "")
            text = cost_file.read_text(encoding="utf-8", errors="replace")
            
            # Extract calls and cost
            calls_match = re.search(r"Total API calls:\s+([\d,]+)", text)
            cost_match = re.search(r"Total cost:\s+\$?([\d.]+)", text)
            
            if calls_match and cost_match:
                calls = int(calls_match.group(1).replace(",", ""))
                cost = float(cost_match.group(1))
                
                safe_stem = stem.replace("_", r"\_")
                rows.append(f"        \\textbf{{F{pdf_idx}:}} \\texttt{{{safe_stem}}} & {calls:,} & ${cost:.6f} \\\\")
                total_calls += calls
                total_cost += cost
                pdf_idx += 1

        latex_cost = [
            "\\begin{table}[h]",
            "    \\centering",
            "    \\caption{API cost per PDF document (Combined Analysis).}",
            "    \\label{tab:api-cost}",
            "    \\begin{tabular}{lrr}",
            "        \\hline",
            "        PDF Document & API Calls & Cost (USD) \\\\",
            "        \\hline"
        ]
        
        latex_cost.extend(rows)
        
        latex_cost.extend([
            "        \\hline",
            f"        \\textbf{{TOTAL}} & {total_calls:,} & ${total_cost:.6f} \\\\",
            "        \\hline",
            "    \\end{tabular}",
            "\\end{table}"
        ])
        
        output_path = self.output_folder / "2_alternative_cost_table.tex"
        output_path.write_text("\n".join(latex_cost), encoding="utf-8")
        print(Fore.GREEN + f"Saved combined LaTeX cost table to {output_path}" + Style.RESET_ALL)

    def generate_token_table(self):
        summary = self.llm_analyzer.get_usage_summary()
        
        # Find all *_cost.txt files to ensure we have all PDFs
        cost_files = sorted(list(self.output_folder.glob("*_cost.txt")))
        
        rows = []
        total_prompt = summary['prompt_tokens']
        total_completion = summary['completion_tokens']
        total_tokens = summary['total_tokens']
        total_calls = summary['calls']
        
        # Add full text analysis row
        rows.append(f"        \\texttt{{Full Text Analysis}} & {summary['prompt_tokens']:,} & {summary['completion_tokens']:,} & {summary['total_tokens']:,} & {summary['calls']:,} \\\\")
        
        pdf_idx = 1
        for cost_file in cost_files:
            if cost_file.name == "full_text_analysis_cost.txt":
                continue
            
            stem = cost_file.stem.replace("_cost", "")
            text = cost_file.read_text(encoding="utf-8", errors="replace")
            
            # Extract metrics
            def find_int(label: str) -> int:
                pattern = rf"{label}:\s+([\d,]+)"
                m = re.search(pattern, text)
                return int(m.group(1).replace(",", "")) if m else 0

            prompt = find_int("Prompt tokens")
            completion = find_int("Completion tokens")
            total = find_int("Total tokens")
            calls = find_int("Total API calls")
            
            if calls > 0:
                safe_stem = stem.replace("_", r"\_")
                rows.append(f"        \\textbf{{F{pdf_idx}:}} \\texttt{{{safe_stem}}} & {prompt:,} & {completion:,} & {total:,} & {calls:,} \\\\")
                total_prompt += prompt
                total_completion += completion
                total_tokens += total
                total_calls += calls
                pdf_idx += 1

        latex_tokens = [
            "\\begin{table}[h]",
            "    \\centering",
            "    \\caption{Token usage per PDF document (Combined Analysis).}",
            "    \\label{tab:token-usage}",
            "    \\begin{tabular}{lrrrr}",
            "        \\hline",
            "        PDF Document & Prompt & Completion & Total & Calls \\\\",
            "        \\hline"
        ]
        latex_tokens.extend(rows)
        latex_tokens.extend([
            "        \\hline",
            f"        \\textbf{{TOTAL}} & {total_prompt:,} & {total_completion:,} & {total_tokens:,} & {total_calls:,} \\\\",
            "        \\hline",
            "    \\end{tabular}",
            "\\end{table}"
        ])
        
        output_path = self.output_folder / "2_alternative_token_table.tex"
        output_path.write_text("\n".join(latex_tokens), encoding="utf-8")
        print(Fore.GREEN + f"Saved combined LaTeX token table to {output_path}" + Style.RESET_ALL)

    def run(self):
        pdf_files = sorted(list(self.source_folder.glob("*.pdf")))
        all_results = {} # {pdf_name: {category: note}}
        
        for pdf_path in pdf_files:
            print(Fore.BLUE + f"\nProcessing {pdf_path.name}..." + Style.RESET_ALL)
            pdf_text = self.extract_text(pdf_path)
            pdf_results = {}
            
            # To keep it simple and avoid hitting rate limits too hard, we process categories sequentially
            # but the user asked for a "concurrent" program. In Python, we can use ThreadPoolExecutor.
            from concurrent.futures import ThreadPoolExecutor
            
            def process_cat(cat_info):
                cat, kws = cat_info
                resp, note = self.analyze_category(pdf_text, cat, kws)
                return cat, note, resp

            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(process_cat, (cat, kws)) for cat, kws in self.categories.items()]
                for future in futures:
                    cat, note, resp = future.result()
                    pdf_results[cat] = note
            
            all_results[pdf_path.stem] = pdf_results
            
        self.generate_latex_tables(all_results)
        self.generate_cost_table()
        self.generate_token_table()
        
        # Save cost summary
        cost_file = self.output_folder / "2_full_text_analysis_cost.txt"
        self.llm_analyzer.print_usage_summary(str(cost_file))

if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Full PDF Analyzer using Gemini 2.5 Pro")
    parser.add_argument("--source", default="/home/aa/CodeRepository/JCC-2026a/Standards", help="Source folder with PDFs")
    parser.add_argument("--keywords", default="cloud.json", help="Path to keywords JSON")
    parser.add_argument("--output", default="/home/aa/CodeRepository/JCC-2026a/Standards", help="Output folder")
    
    args = parser.parse_args()
    
    analyzer = FullPDFAnalyzer(args.source, args.keywords, args.output)
    analyzer.run()