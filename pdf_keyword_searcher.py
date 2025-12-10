import argparse
import re
import sys
import os
from colorama import init, Fore, Style
import pdfplumber

# Initialize colorama for colored output
init(autoreset=True)


def extract_text_smartly(page):
    """
    Extracts text from a page respecting multi-column layouts.
    Detects regions where text spans across columns (like titles) vs two-column regions.
    For two-column regions, reads left column then right column.
    """
    words = page.extract_words()
    width = page.width
    height = page.height
    center = width / 2
    epsilon = 10  # Buffer for center crossing detection

    # Identify words that cross the center gutter (spanning words)
    # A word crosses if it starts before center-buffer and ends after center+buffer
    spanning_words = [
        w for w in words 
        if w['x0'] < center - epsilon and w['x1'] > center + epsilon
    ]

    # Create Y-intervals covered by spanning words
    spanning_intervals = []
    for w in spanning_words:
        spanning_intervals.append((w['top'], w['bottom']))

    # Merge overlapping vertical intervals
    spanning_intervals.sort()
    merged = []
    if spanning_intervals:
        curr_start, curr_end = spanning_intervals[0]
        for start, end in spanning_intervals[1:]:
            if start <= curr_end + 2:  # 2 points vertical tolerance
                curr_end = max(curr_end, end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = start, end
        merged.append((curr_start, curr_end))

    # Construct the full sequence of intervals (Spanning vs Column)
    final_intervals = []
    curr_y = 0
    for start, end in merged:
        # Buffer region before spanning element is a Column region
        if start > curr_y:
            final_intervals.append({'type': 'cols', 'top': curr_y, 'bottom': start})
        # The region covered by spanning element is a Spanning region
        final_intervals.append({'type': 'span', 'top': start, 'bottom': end})
        curr_y = end
    # Remaining region is Column region
    if curr_y < height:
        final_intervals.append({'type': 'cols', 'top': curr_y, 'bottom': height})

    full_text = []
    for interval in final_intervals:
        if interval['bottom'] - interval['top'] < 1:
            continue
        
        # Define the vertical slice for this interval
        # Use crop to isolate the region
        crop_box = (0, interval['top'], width, interval['bottom'])
        
        # Safety check for invalid boxes
        if crop_box[1] >= crop_box[3]:
            continue
            
        try:
            cropped_page = page.crop(crop_box)
        except Exception:
            continue

        if interval['type'] == 'span':
            # Extract normally
            text = cropped_page.extract_text(x_tolerance=2, y_tolerance=2)
            if text:
                full_text.append(text)
        else:
            # Split into Left and Right columns
            # Left Column
            left_box = (0, interval['top'], center, interval['bottom'])
            try:
                left_crop = page.crop(left_box)
                t1 = left_crop.extract_text(x_tolerance=2, y_tolerance=2)
                if t1:
                    full_text.append(t1)
            except Exception:
                pass
            
            # Right Column
            right_box = (center, interval['top'], width, interval['bottom'])
            try:
                right_crop = page.crop(right_box)
                t2 = right_crop.extract_text(x_tolerance=2, y_tolerance=2)
                if t2:
                    full_text.append(t2)
            except Exception:
                pass

    return "\n".join(full_text)


def find_keyword_contexts(file_path, keyword):
    """
    Finds all occurrences of a keyword in a PDF and extracts the sentences where it appears.
    Returns a list of tuples containing (page_num, sentence).
    """
    contexts = []
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            # Use smart extraction to handle columns
            text = extract_text_smartly(page)
            if text:
                # A more robust way to split sentences
                sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|!)\s', text.replace('\n', ' '))
                for i, sentence in enumerate(sentences):
                    if re.search(re.escape(keyword), sentence, re.IGNORECASE):
                        context = ""
                        if i > 0:
                            context += sentences[i-1].strip() + " "
                        context += sentence.strip()
                        if i < len(sentences) - 1:
                            context += " " + sentences[i+1].strip()
                        contexts.append((page_num, context))
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
