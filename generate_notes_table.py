import os
import re
import json
from pathlib import Path
from typing import Dict, List
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

class NotesTableGenerator:
    def __init__(self, source_folder: str, keywords_path: str):
        self.source_folder = Path(source_folder)
        self.keywords_path = Path(keywords_path)
        self.categories = self._load_categories()
        
    def _load_categories(self) -> List[str]:
        with open(self.keywords_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return list(data.keys())

    def extract_note_from_file(self, file_path: Path) -> float:
        """Extracts the NOTE: X value from a result file."""
        if not file_path.exists():
            return 0.0
        
        content = file_path.read_text(encoding='utf-8')
        # Look for NOTE: X or NOTE: X/10
        match = re.search(r'NOTE:\s*([\d.]+)', content)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
        return 0.0

    def run(self):
        # Find all PDF stems by looking at the .pdf files
        pdf_stems = sorted([f.stem for f in self.source_folder.glob("*.pdf")])
        
        # results format: {pdf_stem: {category_name: note}}
        results = {}
        
        print(Fore.CYAN + "Extracting notes from PDFAnalyzer output files..." + Style.RESET_ALL)
        
        for stem in pdf_stems:
            results[stem] = {cat: 0.0 for cat in self.categories}
            
            # PDFAnalyzer saves results in {stem}_all_category_results.txt
            results_file = self.source_folder / f"{stem}_all_category_results.txt"
            if results_file.exists():
                content = results_file.read_text(encoding='utf-8')
                # Split by category processing header
                sections = re.split(r'-------------> Processing category \d+: ', content)
                for section in sections:
                    if not section.strip():
                        continue
                    
                    # Extract category name from the first line of the section
                    lines = section.split('\n')
                    cat_name = lines[0].strip()
                    
                    # Extract note
                    note_match = re.search(r'NOTE:\s*([\d.]+)', section)
                    if note_match and cat_name in results[stem]:
                        results[stem][cat_name] = float(note_match.group(1))
                
        self.generate_latex_table(results)

    def generate_latex_table(self, results: Dict[str, Dict[str, float]]):
        pdf_names = sorted(results.keys())
        cat_names = self.categories
        
        latex = [
            "\\begin{table*}[h]",
            "    \\centering",
            "    \\caption{Evaluation scores for PDFAnalyzer (Snippet-based Analysis - Method 1) per PDF and category.}",
            "    \\label{tab:pdfanalyzer-notes}",
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
                note = results[pdf].get(cat, 0.0)
                row.append(f"{note:.1f}")
                total_note += note
            row.append(f"{total_note:.1f}")
            latex.append("        " + " & ".join(row) + " \\\\")
            
        latex.extend([
            "        \\hline",
            "    \\end{tabular}",
            "\\end{table*}"
        ])
        
        output_path = self.source_folder / "1_pdfanalyzer_summary_notes_table.tex"
        output_path.write_text("\n".join(latex), encoding="utf-8")
        print(Fore.GREEN + f"Saved LaTeX table to {output_path}" + Style.RESET_ALL)

if __name__ == "__main__":
    # Using cloud.json as it contains the 7 categories used in the Standards folder
    generator = NotesTableGenerator(
        source_folder="/home/aa/CodeRepository/JCC-2026a/Standards",
        keywords_path="cloud.json"
    )
    generator.run()