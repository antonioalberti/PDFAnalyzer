#!/usr/bin/env python3
"""
Wrapper script to run pdf_keyword_searcher.py for all keywords from aitaxonomy.json
on all PDF files in the PAPERS folder.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def load_keywords(json_path):
    """Load keywords from the JSON file."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Flatten all keywords from all categories
    keywords = []
    for category, kw_list in data.items():
        keywords.extend(kw_list)
    
    return keywords

def get_pdf_files(papers_dir):
    """Get all PDF files from the papers directory."""
    papers_path = Path(papers_dir)
    return list(papers_path.glob('*.pdf'))

def main():
    parser = argparse.ArgumentParser(
        description="Run keyword search on all PDFs with all keywords from JSON file"
    )
    parser.add_argument(
        '--papers-dir', 
        required=True,
        help='Directory containing PDF files'
    )
    parser.add_argument(
        '--keywords-file',
        required=True,
        help='JSON file containing keywords'
    )
    parser.add_argument(
        '--output-dir',
        default=None,
        help='Directory to save results (default: same as papers directory)'
    )
    parser.add_argument(
        '--script',
        default='pdf_keyword_searcher.py',
        help='Path to pdf_keyword_searcher.py (default: pdf_keyword_searcher.py in current dir)'
    )
    
    args = parser.parse_args()
    
    # Load keywords
    print(f"Loading keywords from {args.keywords_file}...")
    keywords = load_keywords(args.keywords_file)
    print(f"Found {len(keywords)} keywords")
    
    # Get PDF files
    print(f"Scanning for PDFs in {args.papers_dir}...")
    pdf_files = get_pdf_files(args.papers_dir)
    print(f"Found {len(pdf_files)} PDF files")
    
    # Set output directory to papers directory if not specified
    if args.output_dir is None:
        args.output_dir = args.papers_dir
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Summary file
    summary_file = os.path.join(args.output_dir, 'keyword_search_results.txt')
    
    total_searches = len(pdf_files) * len(keywords)
    current = 0
    
    print(f"\nStarting {total_searches} searches...")
    print(f"Results will be saved to {args.output_dir}")
    
    with open(summary_file, 'w', encoding='utf-8') as summary:
        summary.write(f"Keyword Search Summary\n")
        summary.write(f"======================\n")
        summary.write(f"Papers directory: {args.papers_dir}\n")
        summary.write(f"Keywords file: {args.keywords_file}\n")
        summary.write(f"Total PDFs: {len(pdf_files)}\n")
        summary.write(f"Total keywords: {len(keywords)}\n")
        summary.write(f"Total searches: {total_searches}\n\n")
        
        for pdf_file in pdf_files:
            pdf_name = pdf_file.name
            summary.write(f"\n{'='*80}\n")
            summary.write(f"PDF: {pdf_name}\n")
            summary.write(f"{'='*80}\n")
            
            found_any = False
            
            for keyword in keywords:
                current += 1
                
                try:
                    # Run the keyword searcher
                    result = subprocess.run(
                        [sys.executable, args.script, str(pdf_file), keyword],
                        capture_output=True,
                        text=True,
                        timeout=120  # 2 minute timeout per search
                    )
                    
                    output = result.stdout
                    
                    # Check if keyword was found (look for "Found X occurrence(s)")
                    if "Found 0 occurrence" not in output and "occurrence(s)" in output:
                        found_any = True
                        summary.write(f"\n--- Keyword: '{keyword}' ---\n")
                        
                        # Extract the relevant lines
                        lines = output.strip().split('\n')
                        for line in lines:
                            if 'Page' in line or 'Found' in line or (line.strip() and not line.startswith('[')):
                                summary.write(line + '\n')
                    
                except subprocess.TimeoutExpired:
                    summary.write(f"\n--- Keyword: '{keyword}' ---\n")
                    summary.write("TIMEOUT\n")
                except Exception as e:
                    summary.write(f"\n--- Keyword: '{keyword}' ---\n")
                    summary.write(f"ERROR: {str(e)}\n")
            
            if not found_any:
                summary.write("No keywords found in this PDF.\n")
            
            # Progress update
            print(f"Completed {current}/{total_searches} searches ({current*100//total_searches}%)")
    
    print(f"\nSearch complete! Results saved to {summary_file}")
    print(f"Individual results: {args.output_dir}")

if __name__ == "__main__":
    main()
