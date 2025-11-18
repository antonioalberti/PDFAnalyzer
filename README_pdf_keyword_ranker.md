# PDF Keyword Ranker

This standalone script ranks PDF files according to how many keywords from each category (defined in `AIforcoding.json`) appear in their content.

## Requirements
- Python 3.9+
- Dependencies listed in `requirements.txt` (notably `PyPDF2`).

## Usage
```bash
python pdf_keyword_ranker.py <folder_with_pdfs> [--keywords AIforcoding.json] [--top-n 10] [--recursive] [--output rankings.json]
```

### Arguments
- `folder` (positional): directory containing PDF files to analyze.
- `--keywords`: path to the keyword JSON file (defaults to `AIforcoding.json`).
- `--top-n`: number of top-ranked PDFs to display per category (default 10).
- `--recursive`: include PDFs from subdirectories.
- `--output`: optional path to save the rankings as JSON.

## Output
For each category, the script prints the top PDFs (filename + keyword hit count). When `--output` is provided, the same data is stored in JSON format for further processing.
