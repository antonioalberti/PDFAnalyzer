from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from colorama import Fore, Style, init
from dotenv import load_dotenv
from PyPDF2 import PdfReader

from keyword_search import KeywordSearcher
from llm_query import LLMAnalyzer

sys.stdout.reconfigure(encoding="utf-8")

init(autoreset=True)


Occurrence = Tuple[int, str, str, int]
FilteredOccurrence = Tuple[int, str, str]
EnablerKeywords = Dict[str, List[str]]
OccurrencesByEnabler = Dict[str, List[Occurrence]]
FilteredOccurrencesByEnabler = Dict[str, List[FilteredOccurrence]]


def extract_extended_context(text: str, keyword_start: int, keyword_end: int) -> str:
    """Return the surrounding sentences for the keyword occurrence."""

    sentence_endings = re.compile(r"(?<=[.!?])\s+")
    sentences = sentence_endings.split(text)
    current_pos = 0
    sentence_index = None

    for index, sentence in enumerate(sentences):
        sentence_start = current_pos
        sentence_end_pos = sentence_start + len(sentence)
        if sentence_start <= keyword_start <= sentence_end_pos:
            sentence_index = index
            break
        current_pos = sentence_end_pos + 1  # account for the space after punctuation

    if sentence_index is None:
        return sentences[0].strip() if sentences else ""

    previous_sentence = sentences[sentence_index - 1] if sentence_index > 0 else ""
    current_sentence = sentences[sentence_index]
    next_sentence = sentences[sentence_index + 1] if sentence_index < len(sentences) - 1 else ""

    extended_context_parts: List[str] = []
    if previous_sentence:
        extended_context_parts.append(f"Previous sentence: {previous_sentence.strip()}")
    extended_context_parts.append(f"Current sentence: {current_sentence.strip()}")
    if next_sentence:
        extended_context_parts.append(f"Next sentence: {next_sentence.strip()}")

    return "\n".join(extended_context_parts)


def read_pdf(file_path: Path) -> str:
    """Extract text from a PDF, persist it alongside the file, and return the content."""

    pdf = PdfReader(str(file_path))
    text_parts: List[str] = []

    for page_num, page in enumerate(pdf.pages, start=1):
        page_text = page.extract_text()
        print(Fore.CYAN + f"Extracted text from page {page_num}:" + Style.RESET_ALL)
        if page_text:
            text_parts.append(f"Page {page_num}:\n{page_text}\n")
        else:
            print(Fore.YELLOW + "  No text extracted from this page." + Style.RESET_ALL)

    extracted_text = "".join(text_parts)

    output_path = file_path.with_suffix(".txt")
    try:
        output_path.write_text(extracted_text, encoding="utf-8")
        print(Fore.GREEN + f"Saved extracted text to {output_path}" + Style.RESET_ALL)
    except OSError as exc:  # pragma: no cover - defensive logging
        print(
            Fore.RED + f"Warning: Failed to write extracted text to {output_path}: {exc}" + Style.RESET_ALL
        )

    return extracted_text


def load_enabler_keywords(keywords_path: Path) -> EnablerKeywords:
    """Load enabler keywords from a JSON file."""

    with keywords_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Keywords file must contain a JSON object mapping enablers to keyword lists.")

    normalized_data: EnablerKeywords = {}
    for enabler, keywords in data.items():
        if not isinstance(keywords, list):
            raise ValueError(f"Keywords for enabler '{enabler}' must be provided as a list.")
        normalized_data[str(enabler)] = [str(keyword) for keyword in keywords]

    return normalized_data


def deduplicate_occurrences(occurrences: Sequence[Occurrence]) -> List[Occurrence]:
    """Remove duplicate occurrences to avoid redundant LLM calls."""

    seen: set[Tuple[int, str, str]] = set()
    unique_occurrences: List[Occurrence] = []

    for occurrence in occurrences:
        page_num, keyword, paragraph, _ = occurrence
        key = (page_num, keyword, paragraph)
        if key not in seen:
            seen.add(key)
            unique_occurrences.append(occurrence)

    return unique_occurrences


def analyze_occurrences(
    pdf_text: str,
    enabler_occurrences: OccurrencesByEnabler,
    keyword_occurrence_prompt: str,
    llm_analyzer: LLMAnalyzer,
    model_name: str | None,
    debug: bool,
) -> FilteredOccurrencesByEnabler:
    """Filter occurrences using the LLM to keep only significant mentions."""

    filtered_enabler_occurrences: FilteredOccurrencesByEnabler = {
        enabler: [] for enabler in enabler_occurrences
    }

    for enabler, occurrences in enabler_occurrences.items():
        print(
            Fore.YELLOW
            + f"\n\n--------> Processing occurrences for enabler category: {enabler} ({len(occurrences)} occurrences)"
            + Style.RESET_ALL
        )

        for index, (page_num, keyword, paragraph, absolute_start_idx) in enumerate(
            deduplicate_occurrences(occurrences),
            start=1,
        ):
            print(
                Fore.MAGENTA
                + f"\n\n-----> Occurrence {index}: Keyword '{keyword}' on page {page_num}"
                + Style.RESET_ALL
            )
            extended_context = extract_extended_context(
                pdf_text, absolute_start_idx, absolute_start_idx + len(keyword)
            )
            prompt_text = (
                f"{keyword_occurrence_prompt}\n\nEnabler: {enabler}\nKeyword: {keyword}\nContext:\n{extended_context}"
            )

            try:
                if debug:
                    print(Fore.YELLOW + "\n    [DEBUG] Context being sent to LLM:" + Style.RESET_ALL)
                    print(Fore.WHITE + "=" * 80 + Style.RESET_ALL)
                    print(Fore.WHITE + extended_context + Style.RESET_ALL)
                    print(Fore.WHITE + "=" * 80 + Style.RESET_ALL)

                llm_response = llm_analyzer.analyze_single_occurrence(prompt_text, model_name)
                print(Fore.GREEN + f"    LLM response: {llm_response}" + Style.RESET_ALL)
            except Exception as exc:  # pragma: no cover - defensive logging
                print(
                    Fore.RED
                    + f"Warning: LLM call failed for keyword occurrence filtering: {exc}"
                    + Style.RESET_ALL
                )
                continue

            if llm_response and llm_response.strip().lower() == "significant":
                filtered_enabler_occurrences[enabler].append((page_num, keyword, paragraph))

    return filtered_enabler_occurrences


def print_occurrences(enabler_occurrences: FilteredOccurrencesByEnabler) -> int:
    """Display filtered occurrences and return the total number of matches."""

    total_matches_summary = 0
    print(
        Fore.CYAN + "\n\n\n-------------> Keyword RELEVANT occurrences in all the file:" + Style.RESET_ALL
    )

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


def process_category(
    *,
    enabler: str,
    enabler_keywords: Sequence[str],
    occurrences: Sequence[FilteredOccurrence],
    keyword_counter: Counter,
    file_path: Path,
    category_index: int,
    llm_analyzer: LLMAnalyzer,
    final_prompt_template: str,
    model_name: str | None,
    debug: bool,
) -> None:
    """Prepare prompts, call the LLM, and persist results for a single enabler."""

    print(Fore.CYAN + f"\n\n-------------> Processing category: {enabler}" + Style.RESET_ALL)

    enablers_and_keywords_str = f"{enabler}:\n{', '.join(enabler_keywords)}\n\n"

    keyword_counts_lines = [f"{enabler}:"]
    for keyword, count in keyword_counter.items():
        keyword_counts_lines.append(f"  {keyword}: {count}")
    keyword_counts_str = "\n".join(keyword_counts_lines) + "\n\n"

    category_paragraphs = [paragraph for _, _, paragraph in occurrences]
    significant_paragraphs_str = "\n\n".join(category_paragraphs)

    final_prompt = final_prompt_template.replace("{enablers_and_keywords}", enablers_and_keywords_str)
    final_prompt = final_prompt.replace("{keyword_counts}", keyword_counts_str)
    final_prompt_with_paragraphs = final_prompt.replace(
        "{significant_paragraphs}", significant_paragraphs_str
    )

    if debug:
        print(Fore.YELLOW + "\n    [DEBUG] Context being sent to LLM:" + Style.RESET_ALL)
        print(Fore.WHITE + "=" * 80 + Style.RESET_ALL)
        print(Fore.WHITE + significant_paragraphs_str[:2000] + Style.RESET_ALL)
        print(Fore.WHITE + "=" * 80 + Style.RESET_ALL)

    analysis = llm_analyzer.analyze({}, final_prompt_with_paragraphs, None, model_name)

    base_name = file_path.stem
    base_dir = file_path.parent

    prompt_file = base_dir / f"{base_name}_final_prompt_used_category_{category_index}.txt"
    result_file = base_dir / f"{base_name}_final_result_category_{category_index}.txt"
    significant_file = base_dir / f"{base_name}_significant_paragraphs_category_{category_index}.txt"

    prompt_file.write_text(final_prompt_with_paragraphs, encoding="utf-8")
    result_file.write_text(analysis, encoding="utf-8")
    significant_file.write_text("\n\n".join(category_paragraphs), encoding="utf-8")

    print(Fore.GREEN + f"Category {enabler} analysis completed and files saved." + Style.RESET_ALL)


def process_single_pdf(
    file_path: Path | str,
    keywords_path: Path | str,
    min_representative_matches: int = 100,
    model_name: str = "random",
    debug: bool = False,
) -> None:
    """Process a single PDF document and produce per-category analyses."""

    pdf_path = Path(file_path)
    keywords_file_path = Path(keywords_path)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if not keywords_file_path.is_file():
        raise FileNotFoundError(f"Keywords file not found: {keywords_file_path}")

    load_dotenv()
    effective_model = None if model_name == "random" else model_name

    print(Fore.CYAN + f"Reading PDF file: {pdf_path}" + Style.RESET_ALL)
    pdf_text = read_pdf(pdf_path)
    print(Fore.BLUE + "\n\n\n-------------> PDF text extraction completed!!\n\n" + Style.RESET_ALL)

    print(Fore.CYAN + f"Loading keywords from: {keywords_file_path}" + Style.RESET_ALL)
    enabler_keywords = load_enabler_keywords(keywords_file_path)
    print(Fore.GREEN + f"Loaded {len(enabler_keywords)} enabler categories." + Style.RESET_ALL)

    keyword_searcher = KeywordSearcher(enabler_keywords)
    print(Fore.BLUE + "\n\n -> Searching for keyword occurrences in PDF text..." + Style.RESET_ALL)
    enabler_occurrences = keyword_searcher.check_enabler_occurrences(pdf_text)
    total_occurrences = sum(len(occ) for occ in enabler_occurrences.values())
    print(Fore.GREEN + f"Total keyword occurrences found: {total_occurrences}\n\n" + Style.RESET_ALL)

    llm_analyzer = LLMAnalyzer()
    keyword_occurrence_prompt = llm_analyzer.load_prompt("keyword_occurrence_prompt.txt")

    filtered_enabler_occurrences = analyze_occurrences(
        pdf_text,
        enabler_occurrences,
        keyword_occurrence_prompt,
        llm_analyzer,
        effective_model,
        debug,
    )

    total_matches_summary = print_occurrences(filtered_enabler_occurrences)

    if not any(filtered_enabler_occurrences.values()):
        print(
            Fore.RED
            + "None relevant occurrences have been found in the file under analysis."
            + Style.RESET_ALL
        )
        return

    classified_keywords = keyword_searcher.classify_keywords(filtered_enabler_occurrences)

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
        return

    final_prompt_template = llm_analyzer.load_prompt("final_prompt.txt")

    for category_index, enabler in enumerate(filtered_enabler_occurrences.keys(), start=1):
        occurrences = filtered_enabler_occurrences[enabler]
        if not occurrences:
            continue

        process_category(
            enabler=enabler,
            enabler_keywords=enabler_keywords[enabler],
            occurrences=occurrences,
            keyword_counter=classified_keywords.get(enabler, Counter()),
            file_path=pdf_path,
            category_index=category_index,
            llm_analyzer=llm_analyzer,
            final_prompt_template=final_prompt_template,
            model_name=effective_model,
            debug=debug,
        )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Analyze PDF files for mentions of technological enablers"
    )
    parser.add_argument("source_folder", help="The path to the folder containing PDF files")
    parser.add_argument(
        "start_index",
        type=int,
        help="The starting index (0-based) of the PDF file list to process",
    )
    parser.add_argument(
        "end_index",
        type=int,
        help="The ending index (0-based) of the PDF file list to process (inclusive)",
    )
    parser.add_argument(
        "keywords_path",
        help="The path to the JSON file with enabler keywords",
    )
    parser.add_argument(
        "--model",
        default="random",
        help="The LLM model to use for analysis. Use 'random' for random model selection from models.txt, or specify a model like 'openai/gpt-4.1-mini-2025-04-14'",
    )
    parser.add_argument(
        "--min-representative-matches",
        type=int,
        default=100,
        help="Minimum total matches to consider source representative",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable detailed debug output showing full LLM prompts",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for command-line execution."""

    args = parse_arguments()

    source_folder = Path(args.source_folder)
    keywords_path = Path(args.keywords_path)

    if not source_folder.is_dir():
        print(Fore.RED + f"Error: Source folder not found: {source_folder}" + Style.RESET_ALL)
        sys.exit(1)
    if not keywords_path.is_file():
        print(Fore.RED + f"Error: Keywords file not found: {keywords_path}" + Style.RESET_ALL)
        sys.exit(1)

    pdf_files = sorted(
        (
            path
            for path in source_folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: path.name.lower(),
    )

    if not pdf_files:
        print(Fore.YELLOW + "No PDF files found in the provided source folder." + Style.RESET_ALL)
        sys.exit(0)

    max_index = len(pdf_files) - 1
    if args.start_index < 0 or args.end_index > max_index or args.start_index > args.end_index:
        print(Fore.RED + "Error: Invalid start or end index." + Style.RESET_ALL)
        sys.exit(1)

    files_to_process = pdf_files[args.start_index : args.end_index + 1]

    if not files_to_process:
        print(Fore.YELLOW + "No files to process in the specified index range." + Style.RESET_ALL)
        sys.exit(0)

    print(
        Fore.CYAN
        + f"Found {len(pdf_files)} PDF files. Processing files from index {args.start_index} to {args.end_index}:"
        + Style.RESET_ALL
    )
    for relative_index, file_path in enumerate(files_to_process, start=args.start_index):
        print(f"  {relative_index}: {file_path.name}")

    for file_path in files_to_process:
        print(
            Fore.BLUE
            + f"\n\n-------------> Starting processing for file: {file_path.name}"
            + Style.RESET_ALL
        )
        process_single_pdf(
            file_path,
            keywords_path,
            min_representative_matches=args.min_representative_matches,
            model_name=args.model,
            debug=args.debug,
        )
        print(
            Fore.BLUE
            + f"\n-------------> Finished processing for file: {file_path.name}\n\n"
            + Style.RESET_ALL
        )

    print(Fore.GREEN + "All selected files processed." + Style.RESET_ALL)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()