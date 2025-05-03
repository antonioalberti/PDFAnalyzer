import re
from collections import Counter

class KeywordSearcher:
    def __init__(self, enabler_keywords):
        self.enabler_keywords = enabler_keywords

    @staticmethod
    def extract_context(content, start, end):
        # Extract the full paragraph containing the occurrence
        # Split content into paragraphs by double newlines or single newlines
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        for paragraph in paragraphs:
            para_start = content.find(paragraph)
            para_end = para_start + len(paragraph)
            if para_start <= start <= para_end:
                return paragraph
        # Fallback: return the original snippet if no paragraph found
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
            print(f"Processing page number: {page_num}")
            references_start = re.search("REFERENCES", content, re.IGNORECASE)
            if references_start:
                print("  References section found, truncating content.")
                content = content[:references_start.start()]
            for keyword in keywords:
                print(f"  Searching for keyword: '{keyword}'")
                # Use regex with word boundaries for exact whole word match, case-insensitive
                keyword_pattern = re.compile(rf"\\b{re.escape(keyword)}\\b", re.IGNORECASE)
                matches = keyword_pattern.finditer(content)
                found_any = False
                for match in matches:
                    found_any = True
                    context = KeywordSearcher.extract_context(content, match.start(), match.end())
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
