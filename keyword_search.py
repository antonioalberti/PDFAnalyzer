import re
from collections import Counter

class KeywordSearcher:
    def __init__(self, enabler_keywords):
        self.enabler_keywords = enabler_keywords

    @staticmethod
    def _iter_sentences(content):
        sentence_pattern = re.compile(r'[^.!?]*[.!?]|[^.!?]+$', re.DOTALL)
        for match in sentence_pattern.finditer(content):
            sentence = match.group()
            if sentence.strip():
                yield sentence.strip(), match.start(), match.end()

    @staticmethod
    def extract_context(content, start, end):
        for sentence, sentence_start, sentence_end in KeywordSearcher._iter_sentences(content):
            if sentence_start <= start < sentence_end:
                return sentence
        return content[start:end].strip()

    @staticmethod
    def find_occurrences_without_references(text, keywords):
        results = []
        # Use regex to find actual page headers: "Page N:\n" at start of line
        page_pattern = re.compile(r'^Page (\d+):\n', re.MULTILINE)
        
        # Find all page header positions
        page_matches = list(page_pattern.finditer(text))
        
        if not page_matches:
            print("Warning: No page headers found in text.")
            return results

        for i, match in enumerate(page_matches):
            page_num = int(match.group(1))
            page_content_start = match.end()
            
            # Determine where this page's content ends (start of next page or EOF)
            if i + 1 < len(page_matches):
                page_content_end = page_matches[i + 1].start()
            else:
                page_content_end = len(text)
            
            content = text[page_content_start:page_content_end]

            for keyword in keywords:
                keyword_pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
                for kw_match in keyword_pattern.finditer(content):
                    start_idx = kw_match.start()
                    end_idx = kw_match.end()
                    context = KeywordSearcher.extract_context(content, start_idx, end_idx)
                    absolute_start_idx = page_content_start + start_idx
                    results.append((page_num, keyword, context, absolute_start_idx))

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
