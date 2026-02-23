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
    
    # Keep categories and keywords together
    # Returns: (categories_dict, flat_keywords_list)
    categories = {}
    all_keywords = []
    for category, kw_list in data.items():
        categories[category] = kw_list
        all_keywords.extend(kw_list)
    
    return categories, all_keywords

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
    categories, keywords = load_keywords(args.keywords_file)
    category_names = list(categories.keys())
    print(f"Found {len(keywords)} keywords in {len(category_names)} categories")
    
    # Get PDF files
    print(f"Scanning for PDFs in {args.papers_dir}...")
    pdf_files = get_pdf_files(args.papers_dir)
    print(f"Found {len(pdf_files)} PDF files")
    
    # Dictionary to store results: {pdf_name: {category: count}}
    results_summary = {}
    
    # Set output directory to papers directory if not specified
    if args.output_dir is None:
        args.output_dir = args.papers_dir
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Summary file
    summary_file = os.path.join(args.output_dir, 'keyword_search_results.txt')
    
    total_searches = len(pdf_files) * len(keywords)
    current = 0
    pdf_count = len(pdf_files)
    keyword_count = len(keywords)
    
    print(f"\n{'='*60}")
    print(f"KEYWORD SEARCHER - VERBOSE MODE")
    print(f"{'='*60}")
    print(f"Papers directory: {args.papers_dir}")
    print(f"Keywords file: {args.keywords_file}")
    print(f"Output directory: {args.output_dir}")
    print(f"Total PDFs: {pdf_count}")
    print(f"Total keywords: {keyword_count}")
    print(f"Total searches to perform: {total_searches}")
    print(f"{'='*60}\n")
    
    import time
    start_time = time.time()
    
    with open(summary_file, 'w', encoding='utf-8') as summary:
        summary.write(f"Keyword Search Summary\n")
        summary.write(f"======================\n")
        summary.write(f"Papers directory: {args.papers_dir}\n")
        summary.write(f"Keywords file: {args.keywords_file}\n")
        summary.write(f"Total PDFs: {pdf_count}\n")
        summary.write(f"Total keywords: {keyword_count}\n")
        summary.write(f"Total searches: {total_searches}\n\n")
        
        # Initialize category counts for this PDF
        pdf_category_counts = {cat: 0 for cat in category_names}
        
        for pdf_idx, pdf_file in enumerate(pdf_files, 1):
            pdf_name = pdf_file.name
            pdf_start_time = time.time()
            
            print(f"\n[{pdf_idx}/{pdf_count}] Processing PDF: {pdf_name}")
            print(f"-" * 50)
            
            summary.write(f"\n{'='*80}\n")
            summary.write(f"PDF: {pdf_name}\n")
            summary.write(f"{'='*80}\n")
            
            found_any = False
            found_count = 0
            
            # Track which keywords were found and their counts per category
            keyword_counts_per_category = {cat: 0 for cat in category_names}
            
            for kw_idx, keyword in enumerate(keywords, 1):
                current += 1
                
                # Show progress every 10 keywords
                if kw_idx % 10 == 1 or kw_idx == 1:
                    elapsed = time.time() - start_time
                    rate = current / elapsed if elapsed > 0 else 0
                    eta = (total_searches - current) / rate if rate > 0 else 0
                    print(f"  [{kw_idx}/{keyword_count}] Searching: '{keyword}' | Progress: {current}/{total_searches} ({current*100//total_searches}%) | ETA: {eta/60:.1f} min")
                
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
                        found_count += 1
                        
                        # Extract count from output (e.g., "Found 5 occurrence(s)")
                        import re
                        match = re.search(r'Found (\d+) occurrence', output)
                        if match:
                            count = int(match.group(1))
                        else:
                            count = 1
                        
                        # Find which category this keyword belongs to
                        for cat_name, cat_keywords in categories.items():
                            if keyword.lower() in [k.lower() for k in cat_keywords]:
                                keyword_counts_per_category[cat_name] += count
                                break
                        
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
            
            # Store results for this PDF
            results_summary[pdf_name] = keyword_counts_per_category
            
            pdf_elapsed = time.time() - pdf_start_time
            
            # Show category counts for this PDF
            print(f"\n  Category Results for {pdf_name}:")
            print(f"  {'-' * 40}")
            for cat_name, count in keyword_counts_per_category.items():
                if count > 0:
                    print(f"    {cat_name}: {count}")
            print(f"  {'-' * 40}")
            
            if not found_any:
                summary.write("No keywords found in this PDF.\n")
                print(f"  -> Finished: No keywords found | Time: {pdf_elapsed:.1f}s")
            else:
                print(f"  -> Finished: Found keywords in {found_count} matches | Time: {pdf_elapsed:.1f}s")
        
        # Generate CSV summary
        csv_file = os.path.join(args.output_dir, 'keyword_summary_by_category.csv')
        import csv
        with open(csv_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            # Write header
            header = ['Article Title'] + category_names
            writer.writerow(header)
            # Write data rows
            for pdf_name, cat_counts in results_summary.items():
                row = [pdf_name] + [cat_counts[cat] for cat in category_names]
                writer.writerow(row)
        
        print(f"\nCSV summary saved to: {csv_file}")
    
    total_elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"SEARCH COMPLETE!")
    print(f"Total time: {total_elapsed/60:.1f} minutes")
    print(f"Results saved to: {summary_file}")
    print(f"{'='*60}")
    
    print(f"\nSearch complete! Results saved to {summary_file}")
    print(f"Individual results: {args.output_dir}")

if __name__ == "__main__":
    main()
