import argparse
import openai
import re
from collections import Counter
import pdfplumber
from PyPDF2 import PdfReader
import sys
import json
import os
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

def read_pdf(file_path):
    pdf = PdfReader(file_path)
    text = ""
    for page_num, page in enumerate(pdf.pages, start=1):
        text += f"Page {page_num}:\n"
        text += page.extract_text() + "\n"
    return text

def extract_context(content, start, end, num_sentences=3):
    # Find the start of the context by moving backward in the text
    context_start = start
    for _ in range(num_sentences):
        context_start = content.rfind('.', 0, context_start)
        if context_start == -1:
            context_start = 0
            break
        else:
            context_start += 1  # move past the period

    # Find the end of the context by moving forward in the text
    context_end = end
    for _ in range(num_sentences):
        context_end = content.find('.', context_end)
        if context_end == -1:
            context_end = len(content)
            break
        else:
            context_end += 1  # include the period

    return content[context_start:context_end].strip()

def find_occurrences_without_references(text, keywords):
    results = []
    pages = text.split("Page ")
    for page in pages[1:]:
        if ":\n" not in page:
            print(f"Separator not found on page: {page[:100]}...")
            continue

        page_num, content = page.split(":\n", 1)
        references_start = re.search("REFERENCES", content, re.IGNORECASE)
        if references_start:
            content = content[:references_start.start()]
        for keyword in keywords:
            keyword_pattern = re.compile(rf"\b{re.escape(keyword)}\b|\b{re.escape(keyword.replace('-', ' '))}\b", re.IGNORECASE)
            matches = keyword_pattern.finditer(content)
            for match in matches:
                context = extract_context(content, match.start(), match.end())
                results.append((int(page_num), keyword, context))
    return results

def check_enabler_occurrences(pdf_text, enabler_keywords):
    enabler_occurrences = {enabler: [] for enabler in enabler_keywords.keys()}

    for enabler, keywords in enabler_keywords.items():
        enabler_occurrences[enabler] = find_occurrences_without_references(pdf_text, keywords)

    return enabler_occurrences


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


def classify_keywords(enabler_occurrences, enabler_keywords):
    classified_keywords = {enabler: Counter() for enabler in enabler_keywords.keys()}

    for enabler, occurrences in enabler_occurrences.items():
        for _, keyword, _ in occurrences:
            for enabler_key, keywords in enabler_keywords.items():
                if keyword.lower() in [kw.lower() for kw in keywords]:
                    classified_keywords[enabler_key][keyword.lower()] += 1

    return classified_keywords

def load_prompt(prompt_path):
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def analyze_with_requesty(classified_keywords, prompt, abstract):
    import openai

    # Prepare the input text for the model
    input_text = "Keyword Counts:\n"
    for enabler, keyword_counter in classified_keywords.items():
        input_text += f"{enabler}:\n"
        for keyword, count in keyword_counter.items():
            input_text += f"Keyword: {keyword}, Count: {count}\n"
        input_text += "\n"

    # Combine prompt and input text
    full_prompt = prompt + "\n\n" + "Abstract:\n" + abstract + "\n\n" + input_text

    print("\nFull Prompt:")
    print(full_prompt)

    # Initialize OpenAI client for Requesty API
    api_key = os.getenv("ROUTER_API_KEY")
    if not api_key:
        raise ValueError("ROUTER_API_KEY not found in environment variables.")

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://router.requesty.ai/v1",
        default_headers={"Authorization": f"Bearer {api_key}"}
    )

    # Call the chat completion endpoint
    response = client.chat.completions.create(
        model="alibaba/qwen-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": full_prompt}
        ]
    )

    if not response.choices:
        raise Exception("No response choices found.")

    return response.choices[0].message.content.strip()

def main(file_path, keywords_path):
    load_dotenv()  # Load environment variables from .env
    openai.api_key = os.getenv("OPENAI_API_KEY")

    pdf_text = read_pdf(file_path)

    # Load enabler keywords from JSON file
    with open(keywords_path, 'r', encoding='utf-8') as f:
        enabler_keywords = json.load(f)

    # Extract abstract from PDF using pdfplumber for better accuracy
    abstract = ""
    with pdfplumber.open(file_path) as pdf:
        # Search first 3 pages for abstract
        for i in range(min(3, len(pdf.pages))):
            page = pdf.pages[i]
            text = page.extract_text()
            if text:
                # Look for "Abstract" in various capitalizations
                abstract_match = re.search(r"\bAbstract\b|\bABSTRACT\b|\babstract\b", text)
                if abstract_match:
                    start = abstract_match.end()
                    after_abstract = text[start:]
                    # Heuristic: abstract ends at next section heading (all caps line) or double newline
                    match = re.search(r"\n[A-Z][A-Z\s\-]{3,}\n", after_abstract)
                    if match:
                        next_match = re.search(r"\n[A-Z][A-Z\s\-]{3,}\n", after_abstract[match.end():])
                        if next_match:
                            abstract = after_abstract[:match.end() + next_match.start()].strip()
                        else:
                            abstract = after_abstract[:match.start()].strip()
                    else:
                        double_nl = after_abstract.find('\n\n')
                        if double_nl != -1:
                            second_double_nl = after_abstract.find('\n\n', double_nl + 2)
                            if second_double_nl != -1:
                                abstract = after_abstract[:second_double_nl].strip()
                            else:
                                abstract = after_abstract[:double_nl].strip()
                        else:
                            abstract = after_abstract[:600].strip()
                    break
        print(f"Extracted Abstract:\n{abstract}\n")

    enabler_occurrences = check_enabler_occurrences(pdf_text, enabler_keywords)
    total_matches_summary = print_occurrences(enabler_occurrences)

    classified_keywords = classify_keywords(enabler_occurrences, enabler_keywords)

    if any(enabler_occurrences.values()):
        print("Keyword Counts:")
        for enabler, keyword_counter in classified_keywords.items():
            if keyword_counter:
                print(f"{enabler}:")
                for keyword, count in keyword_counter.items():
                    print(f"Keyword: {keyword}, Count: {count}")
                print()
        print(f"Total Matches for All Families: {total_matches_summary}")

        if total_matches_summary < 200:
            print("Small number of total matches... Unrepresentative source")
        else:
            # Load prompt from file
            prompt = load_prompt("prompt.txt")

            # Analyze with OpenAI
            analysis = analyze_with_openai(classified_keywords, prompt, abstract)
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
