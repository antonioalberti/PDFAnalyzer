import re
from collections import Counter

class KeywordSearcher:
    def __init__(self, enabler_keywords):
        self.enabler_keywords = enabler_keywords

    @staticmethod
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

    @staticmethod
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
                keyword_pattern = re.compile(rf"\\b{re.escape(keyword)}\\b|\\b{re.escape(keyword.replace('-', ' '))}\\b", re.IGNORECASE)
                matches = keyword_pattern.finditer(content)
                for match in matches:
                    context = KeywordSearcher.extract_context(content, match.start(), match.end())
                    results.append((int(page_num), keyword, context))
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
