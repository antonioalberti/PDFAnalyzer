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
from abstract_extractor import AbstractExtractor

sys.stdout.reconfigure(encoding='utf-8')

from PyPDF2 import PdfReader

def read_pdf(file_path):
    pdf = PdfReader(file_path)
    text = ""
    for page_num, page in enumerate(pdf.pages, start=1):
        text += f"Page {page_num}:\n"
        text += page.extract_text() + "\n"
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

def main(file_path, keywords_path, min_representative_matches=100):
    load_dotenv()  # Load environment variables from .env
    openai.api_key = os.getenv("ROUTER_API_KEY")

    pdf_text = read_pdf(file_path)

    # Load enabler keywords from JSON file
    with open(keywords_path, 'r', encoding='utf-8') as f:
        enabler_keywords = json.load(f)

    # Extract abstract using AbstractExtractor
    abstract = AbstractExtractor.extract_abstract(file_path)
    print(f"Extracted Abstract:\n{abstract}\n")

    keyword_searcher = KeywordSearcher(enabler_keywords)
    enabler_occurrences = keyword_searcher.check_enabler_occurrences(pdf_text)
    total_matches_summary = print_occurrences(enabler_occurrences)

    classified_keywords = keyword_searcher.classify_keywords(enabler_occurrences)

    if any(enabler_occurrences.values()):
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
            llm_analyzer = LLMAnalyzer()
            prompt = llm_analyzer.load_prompt("final_prompt.txt")
            analysis = llm_analyzer.analyze(classified_keywords, prompt, abstract)
            print("\nOpenAI Analysis:")
            print(analysis)
    else:
        print("None of enablers have been found in the files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a PDF for mentions of technological enablers")
    parser.add_argument("file_path", help="The path to the PDF file to analyze")
    parser.add_argument("keywords_path", help="The path to the JSON file with enabler keywords")
    args = parser.parse_args()
    main(args.file_path, args.keywords_path)
