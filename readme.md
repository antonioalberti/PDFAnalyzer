# PDFAnalyzer

PDFAnalyzer is a powerful toolset designed for the automated thematic analysis of PDF documents. It leverages Large Language Models (LLMs) via the OpenRouter API to identify, categorize, and evaluate technological enablers or any specific themes defined by the user. The tool generates standardized LaTeX tables, making it ideal for researchers and professionals who need to synthesize information from large sets of technical documents.

## Installation

1. **Clone the repository** and navigate to the project folder.
2. **Set up a Virtual Environment** (optional but recommended):
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # Linux/Ubuntu:
   source venv/bin/activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure API Key**:
   Create a `.env` file in the root directory and add your OpenRouter API key:
   ```
   ROUTER_API_KEY=your_api_key_here
   ```

## Analysis Methods

The project provides two complementary methods for document analysis:

### Method 1: Granular Analysis (Snippet-based)
This method extracts specific paragraphs containing user-defined keywords and uses an LLM to evaluate the significance of each occurrence. It is highly precise and cost-effective for large document sets.
```bash
python main.py "path/to/pdfs" [start_index] [end_index] keywords.json
```
*Example:* `python main.py "./documents" 0 10 my_themes.json`

### Method 2: Full-Context Analysis
This method sends the entire text of the PDF to the LLM for a holistic evaluation of each category. It provides a cohesive summary and a qualitative score (0-10) for the document's coverage of the theme.
```bash
python full_pdf_analyzer.py --source "path/to/pdfs" --keywords keywords.json --output "path/to/output"
```

## Companion Article (JCC-2026a)

The per-PDF results produced by `main.py` and `full_pdf_analyzer.py` (notes, occurrences, cost/token logs) are the raw material for the LaTeX tables published in the JCC-2026a paper. The post-processing scripts that consolidate those results into the article's tables — together with the `cloud.json` taxonomy used and the end-to-end pipeline runners — live in the companion repository:

→ **[antonioalberti/PaperPDFAnalyzer](https://github.com/antonioalberti/PaperPDFAnalyzer)**

That repo contains:
- `generate_occurrences.py` — per-PDF and consolidated keyword-occurrence tables
- `generate_cost_summary.py` — consolidated cost/token tables for both methods
- `generate_notes_table.py` — qualitative-score comparison matrix
- `generate_diff_table.py` — Method 1 vs. Method 2 score-diff table
- `run_all_analysis.sh` / `run_all_analysis.ps1` — full pipeline runners
- `cloud.json` — the 7-enabler cloud-computing taxonomy used in the paper

## Key Features

- **Thematic Flexibility**: Define your own categories and keywords in a simple JSON format.
- **Standardized Output**: Automatically generates LaTeX code following scientific publication standards (captions on top, wide table support, bold identifiers).
- **Multi-Model Support**: Easily switch between different LLMs (Gemini, Claude, GPT) via OpenRouter.
- **Cost & Token Tracking**: Detailed logging and reporting of API consumption.

## Requirements

- Python 3.x
- Libraries: `PyPDF2`, `pdfplumber`, `openai`, `requests`, `python-dotenv`, `colorama`.
- OpenRouter API Key.

## Contact

For questions or suggestions, please contact the developer.