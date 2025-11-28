import argparse
import re
import sys
import os
from colorama import init, Fore, Style
from PyPDF2 import PdfReader
from difflib import SequenceMatcher

# Initialize colorama for colored output
init(autoreset=True)

def normalize_text(text):
    """
    Normalize text for comparison by removing extra spaces, hyphens, and other formatting
    """
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    # Remove hyphens that are at the end of lines (common in PDFs) to join words like "signifi- cant"
    text = re.sub(r'-\s+', '', text)
    # Remove any remaining special characters that might cause differences
    text = re.sub(r'[^\w\s.,;:!?()[\]{}"\'-]', '', text)
    return text.lower()

def extract_extended_context(text, keyword, keyword_start):
    """
    Extracts the current sentence containing the found keyword.
    """
    # Split the text into sentences
    # Improved sentence splitting to handle more cases
    sentence_endings = re.compile(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|!)\s')
    sentences = sentence_endings.split(text)
    
    current_pos = 0
    sentence_index = None
    
    for i, sentence in enumerate(sentences):
        # Find this sentence in text starting from current_pos
        found_start = text.find(sentence, current_pos)
        if found_start == -1:
             current_pos += len(sentence)
             continue
             
        sentence_start = found_start
        sentence_end_pos = sentence_start + len(sentence)
        
        if sentence_start <= keyword_start < sentence_end_pos:
             sentence_index = i
             break
        
        current_pos = sentence_end_pos
    
    if sentence_index is None:
         # Fallback
         return sentences[0] if sentences else ""

    # Return only the current sentence as requested
    current_sentence = sentences[sentence_index]
    
    return current_sentence.strip()

def read_pdf(file_path):
    """
    Extracts text from a PDF file and returns it with page markers.
    """
    pdf = PdfReader(file_path)
    text = ""
    for page_num, page in enumerate(pdf.pages, start=1):
        page_text = page.extract_text()
        if page_text:
            text += f"Page {page_num}:\n"
            text += page_text + "\n"
    return text

def find_keyword_contexts(text, keyword):
    """
    Finds all occurrences of a keyword in the text and extracts context for each.
    Returns a list of tuples containing (page_num, context).
    """
    # Case-insensitive search
    keyword_lower = keyword.lower()
    text_lower = text.lower()
    
    contexts = []
    position = 0
    
    # Find all occurrences of the keyword
    while position < len(text_lower):
        found_pos = text_lower.find(keyword_lower, position)
        if found_pos == -1:
            break
            
        # Determine which page this occurrence is on
        page_num = 1
        subset_text = text[:found_pos]
        matches = list(re.finditer(r'Page (\d+):', subset_text))
        if matches:
            page_num = int(matches[-1].group(1))
        
        # Extract context around the keyword
        context = extract_extended_context(text, keyword, found_pos)
        contexts.append((page_num, context))
        
        # Move past this occurrence
        position = found_pos + len(keyword)
    
    # Deduplication logic
    unique_contexts = []
    
    for page_num, context in contexts:
        is_duplicate = False
        normalized_current = normalize_text(context)
        
        for idx, (existing_page, existing_context) in enumerate(unique_contexts):
            normalized_existing = normalize_text(existing_context)
            
            # Check for high similarity or inclusion
            if normalized_current in normalized_existing:
                is_duplicate = True
                break
            elif normalized_existing in normalized_current:
                 # If existing is substring of new, usually we'd keep new (more complete).
                 # But if we strictly want unique sentences and one is just a fragment?
                 # Given we extract whole sentences now, inclusion implies duplication.
                is_duplicate = True
                break
            else:
                ratio = SequenceMatcher(None, normalized_current, normalized_existing).ratio()
                if ratio > 0.8: # Higher threshold since we are comparing single sentences now
                    is_duplicate = True
                    break
        
        if not is_duplicate:
            unique_contexts.append((page_num, context))
    
    return unique_contexts

def main():
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(
        description="Search for a keyword in a PDF file and display the sentence containing each occurrence."
    )
    parser.add_argument("pdf_file", help="Path to the PDF file to search")
    parser.add_argument("keyword", help="Keyword to search for in the PDF file")
    
    args = parser.parse_args()
    
    # Check if the PDF file exists
    if not os.path.exists(args.pdf_file):
        print(Fore.RED + f"Error: The file '{args.pdf_file}' does not exist." + Style.RESET_ALL)
        sys.exit(1)
    
    # Check if the file is a PDF
    if not args.pdf_file.lower().endswith('.pdf'):
        print(Fore.RED + f"Error: The file '{args.pdf_file}' is not a PDF file." + Style.RESET_ALL)
        sys.exit(1)
    
    try:
        # Extract text from PDF
        pdf_text = read_pdf(args.pdf_file)
        
        # Find keyword contexts
        contexts = find_keyword_contexts(pdf_text, args.keyword)
        
        # Display results
        if contexts:
            print(Fore.GREEN + f"Found {len(contexts)} occurrence(s) of '{args.keyword}':" + Style.RESET_ALL)
            
            for page_num, context in contexts:
                print(Fore.YELLOW + f"Page {page_num}:" + Style.RESET_ALL)
                print(Fore.WHITE + context + Style.RESET_ALL)
        else:
            print(Fore.RED + f"No occurrences of '{args.keyword}' found." + Style.RESET_ALL)
    
    except Exception as e:
        print(Fore.RED + f"Error: {str(e)}" + Style.RESET_ALL)
        # sys.exit(1) 

if __name__ == "__main__":
    main()
