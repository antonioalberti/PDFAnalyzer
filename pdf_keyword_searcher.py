import argparse
import re
import sys
import os
from colorama import init, Fore, Style
import pdfplumber

# Initialize colorama for colored output
init(autoreset=True)

def find_keyword_contexts(file_path, keyword):
    """
    Finds all occurrences of a keyword in a PDF and extracts the sentences where it appears.
    Returns a list of tuples containing (page_num, sentence).
    """
    contexts = []
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if text:
                # A more robust way to split sentences
                sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|!)\s', text.replace('\n', ' '))
                for sentence in sentences:
                    if re.search(re.escape(keyword), sentence, re.IGNORECASE):
                        contexts.append((page_num, sentence.strip()))
    return contexts

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
        # Find keyword contexts
        contexts = find_keyword_contexts(args.pdf_file, args.keyword)
        
        # Display results
        if contexts:
            unique_contexts = []
            seen_sentences = set()
            for page_num, sentence in contexts:
                normalized_sentence = normalize_text(sentence)
                if normalized_sentence not in seen_sentences:
                    unique_contexts.append((page_num, sentence))
                    seen_sentences.add(normalized_sentence)
            
            print(Fore.GREEN + f"Found {len(unique_contexts)} occurrence(s) of '{args.keyword}':" + Style.RESET_ALL)
            for page_num, context in unique_contexts:
                print(Fore.YELLOW + f"Page {page_num}:" + Style.RESET_ALL)
                print(Fore.WHITE + context + Style.RESET_ALL)
        else:
            print(Fore.RED + f"No occurrences of '{args.keyword}' found." + Style.RESET_ALL)
    
    except Exception as e:
        print(Fore.RED + f"Error: {str(e)}" + Style.RESET_ALL)
        # sys.exit(1) 

if __name__ == "__main__":
    main()
