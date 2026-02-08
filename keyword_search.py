import re
from collections import Counter

class KeywordSearcher:
    def __init__(self, enabler_keywords):
        self.enabler_keywords = enabler_keywords

    @staticmethod
    def extract_context(content, start, end):
        # Extract the full sentence containing the occurrence
        # Split content into sentences using punctuation marks as delimiters
        sentence_endings = re.compile(r'(?<=[.!?])\s+')
        sentences = sentence_endings.split(content)
        current_pos = 0
        for sentence in sentences:
            sentence_start = current_pos
            sentence_end = sentence_start + len(sentence)
            if sentence_start <= start <= sentence_end:
                return sentence.strip()
            current_pos = sentence_end + 1  # +1 for the space after punctuation
        # Fallback: return the original snippet if no sentence found
        return content[start:end].strip()

    @staticmethod
    def find_occurrences_without_references(text, keywords):
        results = []
        pages = text.split("Page ")
        current_pos = 0

        for page in pages[1:]:
            if ":\n" not in page:
                print(f"Separator not found on page: {page[:100]}...")
                continue

            page_num_str, content = page.split(":\n", 1)
            page_num_match = re.match(r"\d+", page_num_str.strip())
            if not page_num_match:
                print(f"Warning: Could not extract page number from '{page_num_str.strip()}'")
                current_pos += len("Page ") + len(page)
                continue

            page_num = int(page_num_match.group(0))
            page_header_length = len("Page ") + len(page_num_str) + len(":\n")
            page_content_start = current_pos + page_header_length

            for keyword in keywords:
                keyword_pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
                for match in keyword_pattern.finditer(content):
                    start_idx = match.start()
                    end_idx = match.end()
                    context = KeywordSearcher.extract_context(content, start_idx, end_idx)
                    absolute_start_idx = page_content_start + start_idx
                    results.append((page_num, keyword, context, absolute_start_idx))

            current_pos += len("Page ") + len(page)

        return results

    def check_enabler_occurrences(self, pdf_text):
        enabler_occurrences = {enabler: [] for enabler in self.enabler_keywords.keys()}

        for enabler, keywords in self.enabler_keywords.items():
            enabler_occurrences[enabler] = self.find_occurrences_without_references(pdf_text, keywords)

        return enabler_occurrences

    def classify_keywords(self, enabler_occurrences):
        classified_keywords = {enabler: Counter() for enabler in self.enabler_keywords.keys()}

        for enabler, occurrences in enabler_occurrences.items():
            for _, keyword, _ in occurrences:
                for enabler_key, keywords in self.enabler_keywords.items():
                    if keyword.lower() in [kw.lower() for kw in keywords]:
                        classified_keywords[enabler_key][keyword.lower()] += 1

        return classified_keywords
