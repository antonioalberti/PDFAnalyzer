import argparse
import openai
import re
from collections import Counter
import sys
import json
import os
from dotenv import load_dotenv
from colorama import init, Fore, Style

from keyword_search import KeywordSearcher
from llm_query import LLMAnalyzer

sys.stdout.reconfigure(encoding='utf-8')

from PyPDF2 import PdfReader

init(autoreset=True)

def extract_extended_context(text, keyword_start, keyword_end):
    import re
    # Split the text into sentences
    sentence_endings = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_endings.split(text)
    current_pos = 0
    sentence_index = None
    for i, sentence in enumerate(sentences):
        sentence_start = current_pos
        sentence_end_pos = sentence_start + len(sentence)
        if sentence_start <= keyword_start <= sentence_end_pos:
            sentence_index = i
            break
        current_pos = sentence_end_pos + 1  # space after punctuation

    if sentence_index is None:
        # fallback: return only the sentence where the keyword is
        return sentences[0] if sentences else ""

    # get previous, current and next sentence if they exist
    prev_sentence = sentences[sentence_index - 1] if sentence_index > 0 else ""
    current_sentence = sentences[sentence_index]
    next_sentence = sentences[sentence_index + 1] if sentence_index < len(sentences) - 1 else ""

    # concatenate with clear separators
    extended_context = ""
    if prev_sentence:
        extended_context += f"Previous sentence: {prev_sentence.strip()}\n"
    extended_context += f"Current sentence: {current_sentence.strip()}\n"
    if next_sentence:
        extended_context += f"Next sentence: {next_sentence.strip()}\n"

    return extended_context

def read_pdf(file_path):
    pdf = PdfReader(file_path)
    text = ""
    for page_num, page in enumerate(pdf.pages, start=1):
        page_text = page.extract_text()
        print(Fore.CYAN + f"Extracted text from page {page_num}:" + Style.RESET_ALL)
        if page_text:
            snippet = page_text[:10000].replace('\n', ' ')
            print(Fore.GREEN + f"  {snippet}..." + Style.RESET_ALL)
            text += f"Page {page_num}:\n"
            text += page_text + "\n"
        else:
            print(Fore.YELLOW + "  No text extracted from this page." + Style.RESET_ALL)
    #print("\n\n --> Full extracted text found:")
    #print(text[:100000].replace('\n', ' '))
    return text

def print_occurrences(enabler_occurrences):
    total_matches_summary = 0
    print(Fore.CYAN + "\n\n\n-------------> Keyword RELEVANT occurrences in all the file:" + Style.RESET_ALL)
    for enabler, occurrences in enabler_occurrences.items():
        total_matches = len(occurrences)
        print(Fore.YELLOW + f"{enabler} (Total Matches: {total_matches}):" + Style.RESET_ALL)
        total_matches_summary += total_matches
        if occurrences:
            for page_num, keyword, paragraph in occurrences:
                print(Fore.CYAN + f"Page {page_num}:" + Style.RESET_ALL)
                print(Fore.GREEN + f"Keyword: {keyword}" + Style.RESET_ALL)
                print(Fore.WHITE + f"Paragraph: {paragraph}" + Style.RESET_ALL)
                print()
        else:
            print(Fore.RED + "No occurrences found." + Style.RESET_ALL)
        print()
    return total_matches_summary

def main(file_path, keywords_path, min_representative_matches=100, model_name="gpt-4.1-mini-2025-04-14"):
    load_dotenv()  # Load environment variables from .env
    openai.api_key = os.getenv("ROUTER_API_KEY")

    print(Fore.CYAN + f"Reading PDF file: {file_path}" + Style.RESET_ALL)
    pdf_text = read_pdf(file_path)
    print(Fore.BLUE + "\n\n\n-------------> PDF text extraction completed!!\n\n" + Style.RESET_ALL)

    # Load enabler keywords from JSON file
    print(Fore.CYAN + f"Loading keywords from: {keywords_path}" + Style.RESET_ALL)
    with open(keywords_path, 'r', encoding='utf-8') as f:
        enabler_keywords = json.load(f)
    print(Fore.GREEN + f"Loaded {len(enabler_keywords)} enabler categories." + Style.RESET_ALL)

    keyword_searcher = KeywordSearcher(enabler_keywords)
    print(Fore.BLUE + "\n\n -> Searching for keyword occurrences in PDF text..." + Style.RESET_ALL)
    enabler_occurrences = keyword_searcher.check_enabler_occurrences(pdf_text)
    total_occurrences = sum(len(occ) for occ in enabler_occurrences.values())
    print(Fore.GREEN + f"Total keyword occurrences found: {total_occurrences}\n\n" + Style.RESET_ALL)

    llm_analyzer = LLMAnalyzer()
    keyword_occurrence_prompt = llm_analyzer.load_prompt("keyword_occurrence_prompt.txt")

    # Filter occurrences by consulting LLM for each occurrence
    filtered_enabler_occurrences = {enabler: [] for enabler in enabler_occurrences.keys()}

    for enabler, occurrences in enabler_occurrences.items():
        print(Fore.YELLOW + f"\n\n--------> Processing occurrences for enabler category: {enabler} ({len(occurrences)} occurrences)" + Style.RESET_ALL)
        # Deduplicate occurrences to avoid repeated analysis
        seen = set()
        unique_occurrences = []
        for occ in occurrences:
            key = (occ[0], occ[1], occ[2])  # page_num, keyword, paragraph
            if key not in seen:
                seen.add(key)
                unique_occurrences.append(occ)
        for idx, (page_num, keyword, paragraph, absolute_start_idx) in enumerate(unique_occurrences, start=1):
            print(Fore.MAGENTA + f"\n\n-----> Occurrence {idx}: Keyword '{keyword}' on page {page_num}" + Style.RESET_ALL)
            # Calcular contexto estendido usando o texto completo do PDF e índice absoluto
            extended_context = extract_extended_context(pdf_text, absolute_start_idx, absolute_start_idx + len(keyword))
            prompt_text = f"{keyword_occurrence_prompt}\n\nEnabler: {enabler}\nKeyword: {keyword}\nContext:\n{extended_context}"
            try:
                llm_response = llm_analyzer.analyze_single_occurrence(prompt_text, model_name)
                print(Fore.GREEN + f"    LLM response: {llm_response}" + Style.RESET_ALL)
            except Exception as e:
                print(Fore.RED + f"Warning: LLM call failed for keyword occurrence filtering: {e}" + Style.RESET_ALL)
                continue
            if llm_response is not None and llm_response.lower() == "significant":
                filtered_enabler_occurrences[enabler].append((page_num, keyword, paragraph))

    total_matches_summary = print_occurrences(filtered_enabler_occurrences)

    classified_keywords = keyword_searcher.classify_keywords(filtered_enabler_occurrences)

    if any(filtered_enabler_occurrences.values()):
        print(Fore.CYAN + "Keyword Counts:" + Style.RESET_ALL)
        for enabler, keyword_counter in classified_keywords.items():
            if keyword_counter:
                print(Fore.YELLOW + f"{enabler}:" + Style.RESET_ALL)
                for keyword, count in keyword_counter.items():
                    print(Fore.GREEN + f"Keyword: {keyword}, Count: {count}" + Style.RESET_ALL)
                print()
        print(Fore.GREEN + f"Total Matches for All Families: {total_matches_summary}" + Style.RESET_ALL)

        if total_matches_summary < min_representative_matches:
            print(Fore.RED + "Small number of total matches... Unrepresentative source" + Style.RESET_ALL)
        else:
            prompt = llm_analyzer.load_prompt("final_prompt.txt")
            analysis = llm_analyzer.analyze(classified_keywords, prompt, model_name)
            print(Fore.BLUE + "\nFinal Analysis:" + Style.RESET_ALL)
            print(analysis)
    else:
        print(Fore.RED + "None relevant occurences have been found in the file under analysis." + Style.RESET_ALL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a PDF for mentions of technological enablers")
    parser.add_argument("file_path", help="The path to the PDF file to analyze")
    parser.add_argument("keywords_path", help="The path to the JSON file with enabler keywords")
    parser.add_argument("--model", default="gpt-4.1-mini-2025-04-14", help="The LLM model to use for analysis")
    args = parser.parse_args()
    main(args.file_path, args.keywords_path, model_name=args.model)
