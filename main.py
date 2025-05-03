import argparse
import openai
import re
from collections import Counter
import sys
import json
import os
from dotenv import load_dotenv

from keyword_search import KeywordSearcher
from llm_query import LLMAnalyzer

sys.stdout.reconfigure(encoding='utf-8')

from PyPDF2 import PdfReader

def read_pdf(file_path):
    pdf = PdfReader(file_path)
    text = ""
    for page_num, page in enumerate(pdf.pages, start=1):
        page_text = page.extract_text()
        print(f"Extracted text from page {page_num}:")
        if page_text:
            snippet = page_text[:10000].replace('\n', ' ')
            print(f"  {snippet}...")
            text += f"Page {page_num}:\n"
            text += page_text + "\n"
        else:
            print("  No text extracted from this page.")
    #print("\n\n --> Full extracted text found:")
    #print(text[:100000].replace('\n', ' '))
    return text

def print_occurrences(enabler_occurrences):
    total_matches_summary = 0
    for enabler, occurrences in enabler_occurrences.items():
        total_matches = len(occurrences)
        print(f"{enabler} (Total Matches: {total_matches}):")
        total_matches_summary += total_matches
        if occurrences:
            for page_num, keyword, paragraph in occurrences:
                print(f"Page {page_num}:")
                print(f"Keyword: {keyword}")
                print(f"Paragraph: {paragraph}")
                print()
        else:
            print("No occurrences found.")
        print()
    return total_matches_summary

def main(file_path, keywords_path, min_representative_matches=100, model_name="gpt-4.1-mini-2025-04-14"):
    load_dotenv()  # Load environment variables from .env
    openai.api_key = os.getenv("ROUTER_API_KEY")

    print(f"Reading PDF file: {file_path}")
    pdf_text = read_pdf(file_path)
    print("PDF text extraction completed.")

    # Load enabler keywords from JSON file
    print(f"Loading keywords from: {keywords_path}")
    with open(keywords_path, 'r', encoding='utf-8') as f:
        enabler_keywords = json.load(f)
    print(f"Loaded {len(enabler_keywords)} enabler categories.")

    # Extract abstract using AbstractExtractor
    # print("Extracting abstract from PDF...")
    # abstract = AbstractExtractor.extract_abstract(file_path)
    # if abstract:
    #     print(f"Extracted Abstract:\n{abstract}\n")
    # else:
    #     print("No abstract found in the document.\n")

    keyword_searcher = KeywordSearcher(enabler_keywords)
    print("\n\n -> Searching for keyword occurrences in PDF text...")
    enabler_occurrences = keyword_searcher.check_enabler_occurrences(pdf_text)
    total_occurrences = sum(len(occ) for occ in enabler_occurrences.values())
    print(f"Total keyword occurrences found: {total_occurrences}")

    llm_analyzer = LLMAnalyzer()
    keyword_occurrence_prompt = llm_analyzer.load_prompt("keyword_occurrence_prompt.txt")

    # Filter occurrences by consulting LLM for each occurrence
    filtered_enabler_occurrences = {enabler: [] for enabler in enabler_occurrences.keys()}

    for enabler, occurrences in enabler_occurrences.items():
        print(f"Processing occurrences for enabler category: {enabler} ({len(occurrences)} occurrences)")
        for idx, (page_num, keyword, paragraph) in enumerate(occurrences, start=1):
            print(f"\n\n-----> Occurrence {idx}: Keyword '{keyword}' on page {page_num}")
            prompt_text = f"{keyword_occurrence_prompt}\n\nKeyword: {keyword}\nParagraph: {paragraph}"
            try:
                llm_response = llm_analyzer.analyze_single_occurrence(prompt_text, model_name)
                print(f"    LLM response: {llm_response}")
            except Exception as e:
                print(f"Warning: LLM call failed for keyword occurrence filtering: {e}")
                continue
            if llm_response is not None and llm_response.lower() == "significant":
                filtered_enabler_occurrences[enabler].append((page_num, keyword, paragraph))

    total_matches_summary = print_occurrences(filtered_enabler_occurrences)

    classified_keywords = keyword_searcher.classify_keywords(filtered_enabler_occurrences)

    if any(filtered_enabler_occurrences.values()):
        print("Keyword Counts:")
        for enabler, keyword_counter in classified_keywords.items():
            if keyword_counter:
                print(f"{enabler}:")
                for keyword, count in keyword_counter.items():
                    print(f"Keyword: {keyword}, Count: {count}")
                print()
        print(f"Total Matches for All Families: {total_matches_summary}")

        if total_matches_summary < min_representative_matches:
            print("Small number of total matches... Unrepresentative source")
        else:
            prompt = llm_analyzer.load_prompt("final_prompt.txt")
            analysis = llm_analyzer.analyze(classified_keywords, prompt, abstract, model_name)
            print("\nFinal Analysis:")
            print(analysis)
    else:
        print("None of enablers have been found in the files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a PDF for mentions of technological enablers")
    parser.add_argument("file_path", help="The path to the PDF file to analyze")
    parser.add_argument("keywords_path", help="The path to the JSON file with enabler keywords")
    parser.add_argument("--model", default="gpt-4.1-mini-2025-04-14", help="The LLM model to use for analysis")
    args = parser.parse_args()
    main(args.file_path, args.keywords_path, model_name=args.model)
