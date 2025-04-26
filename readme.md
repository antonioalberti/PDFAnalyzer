# PDFAnalyzer

This project is a tool to analyze PDF documents for mentions of specific technological enablers.

## How to use

1. Place the `main.py` and `run.bat` files in the same folder where the PDF files you want to analyze are located.
2. The PDF files must be named numerically as `0.PDF`, `1.PDF`, `2.PDF`, and so on.
3. Run the `run.bat` file in the Windows command prompt (CMD). This will process all PDFs numbered from 0 to 42, generating text files with the analysis results for each PDF.

## What the script does

- The `main.py` script reads each PDF, extracts the text from each page, and searches for keywords related to different categories of technological enablers.
- For each occurrence found, the script prints the page, the keyword, and a snippet of context from the text.
- The results are saved in `.txt` files corresponding to each analyzed PDF.

## Requirements

- Python 3.x
- PyPDF2 library (can be installed via `pip install PyPDF2`)

## Notes

- The script excludes the references section of the PDFs to avoid false positives.
- The range of files processed in `run.bat` can be adjusted as needed.

## Contact

For questions or suggestions, please contact the developer.
