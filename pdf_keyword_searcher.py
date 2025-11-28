import argparse
import re
import sys
import os
from colorama import init, Fore, Style
from PyPDF2 import PdfReader

# Initialize colorama for colored output
init(autoreset=True)

def extract_extended_context(text, keyword, keyword_start):
    """
    Extracts the previous sentence, current sentence (with keyword), and next sentence
    around the found keyword in the text.
    """
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

    # Format context concisely
    context_parts = []
    if prev_sentence:
        context_parts.append(prev_sentence.strip())
    context_parts.append(f"[{keyword}]" + current_sentence.replace(keyword, f"[{keyword}]", 1))
    if next_sentence:
        context_parts.append(next_sentence.strip())
    
    return " | ".join(context_parts)

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
        page_start = 0
        for line in text.split('\n'):
            if line.startswith('Page ') and line.endswith(':'):
                page_start = text.find(line, page_start)
                if found_pos >= page_start:
                    page_num = int(line.split()[1][:-1])
                else:
                    break
        
        # Extract context around the keyword
        context = extract_extended_context(text, keyword, found_pos)
        contexts.append((page_num, context))
        
        # Move past this occurrence
        position = found_pos + len(keyword)
    
    return contexts

def main():
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(
        description="Search for a keyword in a PDF file and display context around each occurrence."
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
        sys.exit(1)

if __name__ == "__main__":
    main()
