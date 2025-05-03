# PDFAnalyzer

This project is a tool to analyze PDF documents for mentions of specific technological enablers, combining keyword search and AI-powered analysis.

## How to use

1. Place the `main.py`, `run.bat`, and `6G.json` files in the same folder where the PDF files you want to analyze are located.
2. The PDF files must be named numerically as `p0.pdf`, `p1.pdf`, `p2.pdf`, and so on.
3. Run the `install.ps1` PowerShell script to set up a Python virtual environment and install dependencies.
4. Run the `run.bat` file in the Windows command prompt (CMD) with the following arguments:
   ```
   run.bat [source_folder] [max_files] [min_representative_matches]
   ```
   For example:
   ```
   run.bat C:\Users\alberti\Documents\Artigos 42 100
   ```
   This will process PDF files from `p0.pdf` to `p42.pdf` in the specified folder, generating text files with the analysis results for each PDF.

## What the script does

- The `main.py` script reads each PDF, extracts the text from each page, and searches for keywords related to different categories of technological enablers.
- It extracts the abstract section from the first pages of the PDF for contextual analysis.
- For each occurrence found, the script prints the page, the keyword, and a snippet of context from the text.
- The script classifies and counts keyword occurrences by enabler category.
- If the total matches exceed the minimum representative threshold, it uses an AI language model (via the OpenAI API on requesty.ai) to generate an advanced analysis based on the keywords and abstract.
- The results are saved in `.txt` files corresponding to each analyzed PDF.

## Requirements

- Python 3.x
- PyPDF2 and pdfplumber libraries (install via `pip install -r requirements.txt`)
- An OpenAI API key set as `ROUTER_API_KEY` in a `.env` file

## Notes

- The script excludes the references section of the PDFs to avoid false positives.
- The range of files processed in `run.bat` can be adjusted as needed.
- The `install.ps1` script sets up a Python virtual environment and installs all dependencies.

## Contact

For questions or suggestions, please contact the developer.
