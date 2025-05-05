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
        print(f"Total pages found: {len(pages)-1}")
        for page in pages[1:]:
            if ":\n" not in page:
                print(f"Separator not found on page: {page[:100]}...")
                continue

            page_num, content = page.split(":\n", 1)
            print(f"\n --> Processing page number: {page_num}")
            references_start = re.search("REFERENCES", content, re.IGNORECASE)
            if references_start:
                print("  References section found, truncating content.")
                content = content[:references_start.start()]
            for keyword in keywords:
                print(f"  Searching for keyword: '{keyword}'")
                # Use regex with word boundaries for exact whole word match, case-insensitive
                keyword_pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
                matches = list(keyword_pattern.finditer(content))
                found_any = False
                for match in matches:
                    found_any = True
                    start_idx = match.start()
                    end_idx = match.end()
                    context = KeywordSearcher.extract_context(content, start_idx, end_idx)
                    results.append((int(page_num), keyword, context))
                if not found_any:
                    print(f"    Keyword '{keyword}' not found on this page.")
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
